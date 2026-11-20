"""Read-only cross-client conversation scanner without model calls.

Scans Claude Code, Codex (0.169+ SQLite and legacy rollouts), and Antigravity
local conversation stores for the last N days, classifies user vs external worker
vs internal subagent sessions, and marks user sessions missing from the vault's
Oturumlar/ or Devir/ cards as unregistered ("kayitsiz").
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import unicodedata
import urllib.parse
import urllib.request

DEFAULT_DAYS = 10
USER_PREVIEW_CHARS = 160
AGENT_PREVIEW_CHARS = 200

_BIDI_CONTROLS = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
_SYSTEM_REMINDER_RE = re.compile(r"<system-reminder\b[^>]*>.*?</system-reminder>", re.I | re.S)
_SUBSEC_RE = re.compile(r"(\.\d{6})\d+")
_TOKEN8_RE = re.compile(r"[0-9a-zA-Z]{8,}")
_CLAUDE_SKIP_PREFIXES = (
    "<task-notification>",
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<command-name>",
    "Base directory for this skill",
    "[Request interrupted",
)
_CODEX_SKIP_PREFIXES = (
    "# AGENTS.md instructions",
    "<environment_context>",
    "<user_instructions>",
    "<INSTRUCTIONS>",
    "<turn_aborted>",
    "<system-reminder>",
)
_CLAUDE_WORKER_ENTRYPOINTS = frozenset({"sdk-cli", "sdk-ts", "sdk-py", "claude-p", "print", "headless", "worker"})
_CLAUDE_SYNTHETIC_ORIGINS = frozenset({"task_notification", "task-notification", "peer", "host_synthetic", "coordinator"})


def _sanitize_text(text):
    if text is None:
        return ""
    cleaned = _SYSTEM_REMINDER_RE.sub("", str(text))
    cleaned = "".join(
        " " if ch in "\r\n\t" else ("" if unicodedata.category(ch) == "Cc" or ch in _BIDI_CONTROLS else ch)
        for ch in cleaned
    )
    return " ".join(cleaned.split())


def _clip(text, limit=USER_PREVIEW_CHARS):
    cleaned = _sanitize_text(text)
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(1, limit - 1)].rstrip() + "…"


def _parse_ts(value):
    """Parse Unix sec/ms or ISO-8601 timestamp into aware UTC datetime, or None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        sec = value / 1000.0 if value > 1e12 else float(value)
        try:
            dt = datetime.fromtimestamp(sec, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
        return dt if dt.year >= 1970 else None
    text = str(value).strip()
    if not text or text.startswith("0001-"):
        return None
    try:
        num = float(text)
    except ValueError:
        num = None
    if num is not None:
        return _parse_ts(num)
    normalized = _SUBSEC_RE.sub(r"\1", text.replace("Z", "+00:00"))
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt if dt.year >= 1970 else None


def _local_stamp(iso_text):
    dt = _parse_ts(iso_text)
    if dt is None:
        return str(iso_text or "")[:16].replace("T", " ")
    try:
        return f"{dt.astimezone():%Y-%m-%d %H:%M}"
    except (OSError, OverflowError, ValueError):
        return f"{dt:%Y-%m-%d %H:%M}"


def _uri_to_path(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("file://"):
        parsed = urllib.parse.urlsplit(text)
        path = urllib.request.url2pathname(parsed.path)
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            path = f"//{parsed.netloc}{path}"
        return path
    return text


def _read_sqlite(db_path, reader_fn):
    """Read SQLite via ?mode=ro URI; on lock/failure copy to temp dir and retry.

    Returns (result, error_message). Missing file -> (None, None).
    Unreadable even via temporary copy -> (None, reason).
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        return None, None
    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=0.5)
        try:
            conn.execute("PRAGMA query_only=ON")
            return reader_fn(conn), None
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        pass
    try:
        with tempfile.TemporaryDirectory(prefix="beyin-sohbetler-") as tmp:
            tmp_dir = Path(tmp)
            tmp_db = tmp_dir / db_path.name
            shutil.copy2(db_path, tmp_db)
            for suffix in ("-wal", "-shm"):
                sibling = db_path.with_name(db_path.name + suffix)
                if sibling.is_file():
                    try:
                        shutil.copy2(sibling, tmp_dir / sibling.name)
                    except OSError:
                        pass
            tmp_uri = tmp_db.resolve().as_uri() + "?mode=ro"
            try:
                conn = sqlite3.connect(tmp_uri, uri=True, timeout=0.5)
                try:
                    conn.execute("PRAGMA query_only=ON")
                    return reader_fn(conn), None
                finally:
                    conn.close()
            except sqlite3.Error:
                conn = sqlite3.connect(str(tmp_db), timeout=0.5)
                try:
                    return reader_fn(conn), None
                finally:
                    conn.close()
    except (sqlite3.Error, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _table_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _orkestrator_is_kimlikleri():
    """Dış orkestratörün (ör. pasla) açtığı işçi oturumlarının kimlikleri.

    pasla her işi `<PASLA_STATE>/jobs/<id>.json` olarak kaydeder; Codex işinde arka uç oturumu
    ayrıca `thread` alanındadır. Çalışma kopyası olmadan açılan işçiler başka bir izle ayırt
    edilemediği için bu liste olmadan kullanıcı oturumu sayılırdı. `BEYIN_ISCI_KAYITLARI`
    başka bir klasör gösterebilir; klasör yoksa boş küme.
    """
    ham = os.environ.get("BEYIN_ISCI_KAYITLARI") or os.environ.get("PASLA_STATE")
    klasor = Path(ham).expanduser() / "jobs" if ham and not os.environ.get("BEYIN_ISCI_KAYITLARI") else (
        Path(ham).expanduser() if ham else Path.home() / ".local" / "state" / "pasla" / "jobs")
    kimlikler = set()
    try:
        dosyalar = list(klasor.glob("*.json")) if klasor.is_dir() else []
    except OSError:
        return kimlikler
    for dosya in dosyalar:
        try:
            meta = json.loads(dosya.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict):
            for alan in ("id", "thread"):
                deger = meta.get(alan)
                if isinstance(deger, str) and deger:
                    kimlikler.add(deger)
    return kimlikler


def _no_memory_ids(state):
    if not state:
        return set()
    path = Path(state) / "no-memory-sessions.txt"
    try:
        if not path.is_file():
            return set()
        return {line.split("\t", 1)[0].strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()}
    except OSError:
        return set()


def _claude_dir(override=None):
    if override is not None:
        return Path(override).expanduser()
    env_dir = os.environ.get("BEYIN_SOHBETLER_CLAUDE_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    if cfg:
        return Path(cfg).expanduser() / "projects"
    return Path.home() / ".claude" / "projects"


def _codex_paths(codex_dir=None, state_db=None, history_db=None, sessions_dir=None):
    if codex_dir is not None:
        base = Path(codex_dir).expanduser()
    elif os.environ.get("BEYIN_SOHBETLER_CODEX_DIR"):
        base = Path(os.environ["BEYIN_SOHBETLER_CODEX_DIR"]).expanduser()
    elif os.environ.get("CODEX_HOME"):
        base = Path(os.environ["CODEX_HOME"]).expanduser()
    else:
        base = Path.home() / ".codex"
    s_db = Path(state_db).expanduser() if state_db is not None else Path(os.environ.get("BEYIN_SOHBETLER_CODEX_STATE_DB") or (base / "state_5.sqlite")).expanduser()
    h_db = Path(history_db).expanduser() if history_db is not None else Path(os.environ.get("BEYIN_SOHBETLER_CODEX_HISTORY_DB") or (base / "thread_history_1.sqlite")).expanduser()
    sess = Path(sessions_dir).expanduser() if sessions_dir is not None else Path(os.environ.get("BEYIN_SOHBETLER_CODEX_SESSIONS_DIR") or (base / "sessions")).expanduser()
    return s_db, h_db, sess


def _antigravity_db(override=None):
    if override is not None:
        return Path(override).expanduser()
    env_db = os.environ.get("BEYIN_SOHBETLER_ANTIGRAVITY_DB")
    if env_db:
        return Path(env_db).expanduser()
    env_dir = os.environ.get("BEYIN_SOHBETLER_ANTIGRAVITY_DIR")
    if env_dir:
        return Path(env_dir).expanduser() / "conversation_summaries.db"
    return Path.home() / ".gemini" / "antigravity" / "conversation_summaries.db"


def _make_record(istemci, oturum_id, baslangic, bitis, cwd, user_msgs, last_agent_msg, tur, baslik=""):
    first_user = _clip(user_msgs[0], USER_PREVIEW_CHARS) if user_msgs else ""
    last_user = _clip(user_msgs[-1], USER_PREVIEW_CHARS) if user_msgs else ""
    return {
        "istemci": istemci,
        "oturum_id": oturum_id,
        "id8": oturum_id[:8],
        "baslangic": baslangic.astimezone(timezone.utc).isoformat(),
        "bitis": bitis.astimezone(timezone.utc).isoformat(),
        "cwd": cwd or "",
        "baslik": _clip(baslik, 120) if baslik else "",
        "kullanici_mesaj_sayisi": len(user_msgs),
        "ilk_kullanici_mesaji": first_user,
        "son_kullanici_mesaji": last_user,
        "son_ajan_mesaji": _clip(last_agent_msg, AGENT_PREVIEW_CHARS),
        "tur": tur,
    }


def _claude_extract_user_text(content):
    if isinstance(content, str):
        raw = content
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return ""
        raw = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    else:
        return ""
    stripped = _SYSTEM_REMINDER_RE.sub("", raw).strip()
    if not stripped or stripped.startswith(_CLAUDE_SKIP_PREFIXES):
        return ""
    return stripped


def _claude_extract_assistant_text(content):
    if isinstance(content, str):
        raw = content
    elif isinstance(content, list):
        raw = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    else:
        return ""
    return _SYSTEM_REMINDER_RE.sub("", raw).strip()


def read_claude(claude_dir=None, cutoff=None, now=None, no_memory_ids=None):
    """Read Claude Code session transcripts from ~/.claude/projects."""
    root = _claude_dir(claude_dir)
    if not root.is_dir():
        return [], None
    records = []
    use_mtime_filter = now is None and cutoff is not None
    cutoff_epoch = cutoff.timestamp() - 86400 if cutoff is not None else None
    try:
        candidates = sorted(root.rglob("*.jsonl"))
    except OSError as exc:
        return [], f"{type(exc).__name__}: {exc}"

    for path in candidates:
        try:
            if path.is_symlink() or not path.is_file():
                continue
            stat_info = path.stat()
            if use_mtime_filter and stat_info.st_mtime < cutoff_epoch:
                continue
            rel_parts = path.relative_to(root).parts
        except OSError:
            continue

        is_subagent_path = "subagents" in rel_parts or path.stem.startswith("agent-")
        session_id = ""
        agent_id = ""
        cwd = ""
        title = ""
        entrypoints = set()
        perm_modes = set()
        worker_flag = False
        all_ts = []
        parsed_msgs = []  # (is_sidechain, role, ts, text)

        try:
            with path.open("r", encoding="utf-8", errors="ignore") as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(d, dict):
                        continue
                    ts = _parse_ts(d.get("timestamp"))
                    if ts is not None:
                        all_ts.append(ts)
                    if not cwd and isinstance(d.get("cwd"), str) and d["cwd"]:
                        cwd = d["cwd"]
                    if not session_id and isinstance(d.get("sessionId"), str) and d["sessionId"]:
                        session_id = d["sessionId"]
                    if not agent_id and isinstance(d.get("agentId"), str) and d["agentId"]:
                        agent_id = d["agentId"]
                    ep = d.get("entrypoint")
                    if isinstance(ep, str) and ep:
                        entrypoints.add(ep)
                    pm = d.get("permissionMode")
                    if isinstance(pm, str) and pm:
                        perm_modes.add(pm)
                    if d.get("isPrint") is True or d.get("print") is True or d.get("nonInteractive") is True:
                        worker_flag = True
                    kind = d.get("type")
                    if kind == "custom-title" and isinstance(d.get("customTitle"), str) and d["customTitle"]:
                        title = d["customTitle"]
                    elif not title and isinstance(d.get("slug"), str) and d["slug"]:
                        title = d["slug"]

                    if kind == "user":
                        if d.get("isMeta") is True or d.get("isCompactSummary") is True or d.get("isVisibleInTranscriptOnly") is True:
                            continue
                        origin = d.get("origin")
                        origin_kind = origin.get("kind") if isinstance(origin, dict) else origin
                        if d.get("turnOrigin") in _CLAUDE_SYNTHETIC_ORIGINS or origin_kind in _CLAUDE_SYNTHETIC_ORIGINS:
                            continue
                        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
                        text = _claude_extract_user_text(msg.get("content"))
                        if text:
                            parsed_msgs.append((bool(d.get("isSidechain")), "user", ts, text))
                    elif kind == "assistant":
                        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
                        text = _claude_extract_assistant_text(msg.get("content"))
                        if text:
                            parsed_msgs.append((bool(d.get("isSidechain")), "assistant", ts, text))
        except OSError:
            continue

        if not parsed_msgs:
            continue
        has_main = any(not sc for sc, _, _, _ in parsed_msgs)
        is_sidechain_session = is_subagent_path or not has_main
        selected = parsed_msgs if is_sidechain_session else [m for m in parsed_msgs if not m[0]]
        user_msgs = [text for _, role, _, text in selected if role == "user"]
        agent_msgs = [text for _, role, _, text in selected if role == "assistant"]
        if not user_msgs and not agent_msgs:
            continue

        msg_ts = [ts for _, _, ts, _ in selected if ts is not None] or all_ts
        if msg_ts:
            baslangic, bitis = min(msg_ts), max(msg_ts)
        else:
            fallback = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc)
            baslangic, bitis = fallback, fallback
        if cutoff is not None and bitis < cutoff:
            continue

        if is_sidechain_session:
            oturum_id = agent_id or path.stem
            tur = "ic_ajan"
        else:
            oturum_id = session_id or path.stem
            if (
                (entrypoints & _CLAUDE_WORKER_ENTRYPOINTS)
                or worker_flag
                or "dontAsk" in perm_modes
                or "-pasla-" in cwd.casefold()
                or "-pasla-" in path.parent.name.casefold()
                or (no_memory_ids and oturum_id in no_memory_ids)
            ):
                tur = "isci"
            else:
                tur = "kullanici"

        records.append(
            _make_record(
                "claude",
                oturum_id,
                baslangic,
                bitis,
                cwd,
                user_msgs,
                agent_msgs[-1] if agent_msgs else "",
                tur,
                baslik=title,
            )
        )
    return records, None


def _codex_classify(thread_source, source, originator=None):
    ts = thread_source.strip().lower() if isinstance(thread_source, str) else ""
    if ts in ("subagent", "guardian_review"):
        return "ic_ajan"
    if isinstance(source, dict) and "subagent" in source:
        return "ic_ajan"
    if isinstance(source, str) and source.strip().startswith('{"subagent"'):
        return "ic_ajan"
    if ts == "user":
        return "kullanici"
    src = source.strip().lower() if isinstance(source, str) else ""
    orig = originator.strip().lower() if isinstance(originator, str) else ""
    if not ts and (src == "vscode" or orig == "pasla"):
        return "isci"
    if not ts and src == "exec":
        return "isci"
    return "kullanici"


def _codex_item_text(item_json):
    try:
        data = json.loads(item_json)
    except (TypeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    if isinstance(data.get("text"), str):
        raw = data["text"]
    elif isinstance(data.get("content"), list):
        raw = "\n".join(x.get("text", "") for x in data["content"] if isinstance(x, dict) and isinstance(x.get("text"), str))
    elif isinstance(data.get("content"), str):
        raw = data["content"]
    else:
        return ""
    return _SYSTEM_REMINDER_RE.sub("", raw).strip()


def _parse_codex_rollout(path):
    """Parse a Codex rollout .jsonl (session_meta + event_msg + response_item fallback)."""
    meta = {}
    ev_user, ev_agent = [], []
    resp_user, resp_agent = [], []
    task_complete_agent = ""
    all_ts = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                ts = _parse_ts(d.get("timestamp"))
                if ts is not None:
                    all_ts.append(ts)
                kind = d.get("type")
                p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
                if kind == "session_meta":
                    if not meta:
                        meta = dict(p)
                    if p.get("timestamp"):
                        mts = _parse_ts(p["timestamp"])
                        if mts is not None:
                            all_ts.append(mts)
                elif kind == "event_msg":
                    pt = p.get("type")
                    if pt == "user_message":
                        txt = _SYSTEM_REMINDER_RE.sub("", str(p.get("message") or p.get("text") or "")).strip()
                        if txt and not txt.startswith(_CODEX_SKIP_PREFIXES):
                            ev_user.append(txt)
                    elif pt == "agent_message":
                        txt = _SYSTEM_REMINDER_RE.sub("", str(p.get("message") or p.get("text") or "")).strip()
                        if txt:
                            ev_agent.append(txt)
                    elif pt == "task_complete" and isinstance(p.get("last_agent_message"), str) and p["last_agent_message"].strip():
                        task_complete_agent = _SYSTEM_REMINDER_RE.sub("", p["last_agent_message"]).strip()
                elif kind == "response_item" and p.get("type") == "message":
                    role = p.get("role")
                    content = p.get("content")
                    if isinstance(content, list):
                        raw = "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and isinstance(x.get("text"), str))
                    elif isinstance(content, str):
                        raw = content
                    else:
                        raw = ""
                    txt = _SYSTEM_REMINDER_RE.sub("", raw).strip()
                    if not txt:
                        continue
                    if role == "user" and not txt.startswith(_CODEX_SKIP_PREFIXES):
                        resp_user.append(txt)
                    elif role == "assistant":
                        resp_agent.append(txt)
    except OSError:
        return None

    user_msgs = ev_user if ev_user else resp_user
    agent_msgs = ev_agent if ev_agent else resp_agent
    last_agent = agent_msgs[-1] if agent_msgs else task_complete_agent
    sid = str(meta.get("id") or meta.get("session_id") or "")
    if not sid:
        m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", path.stem, re.I)
        sid = m.group(1) if m else path.stem
    return {
        "id": sid,
        "cwd": str(meta.get("cwd") or ""),
        "thread_source": meta.get("thread_source"),
        "source": meta.get("source"),
        "originator": meta.get("originator"),
        "timestamps": all_ts,
        "user_msgs": user_msgs,
        "last_agent": last_agent,
    }


def _read_codex_state(conn):
    if "threads" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        return {}
    cols = _table_columns(conn, "threads")
    wanted = ["id", "created_at", "updated_at", "created_at_ms", "updated_at_ms", "cwd", "title", "name",
              "thread_source", "source", "model", "originator", "first_user_message", "rollout_path"]
    selected = [c for c in wanted if c in cols]
    if "id" not in selected:
        return {}
    threads = {}
    for row in conn.execute(f"SELECT {', '.join(selected)} FROM threads"):
        item = dict(zip(selected, row))
        tid = str(item.get("id") or "")
        if tid:
            threads[tid] = item
    return threads


def _read_codex_history(conn, target_ids=None):
    if "thread_items" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        return {}
    cols = _table_columns(conn, "thread_items")
    if not {"thread_id", "item_type", "item_json"} <= cols:
        return {}
    order_col = "rollout_ordinal ASC, rowid ASC" if "rollout_ordinal" in cols else "rowid ASC"
    time_select = ", created_at_ms" if "created_at_ms" in cols else ""
    out = {}

    def consume(rows):
        for row in rows:
            tid, itype, ijson = row[0], row[1], row[2]
            ctime = row[3] if len(row) > 3 else None
            entry = out.setdefault(tid, {"user_msgs": [], "last_agent": "", "timestamps": []})
            ts = _parse_ts(ctime)
            if ts is not None:
                entry["timestamps"].append(ts)
            text = _codex_item_text(ijson)
            if not text:
                continue
            if itype == "userMessage" and not text.startswith(_CODEX_SKIP_PREFIXES):
                entry["user_msgs"].append(text)
            elif itype == "agentMessage":
                entry["last_agent"] = text

    if target_ids is None:
        consume(conn.execute(
            f"SELECT thread_id, item_type, item_json{time_select} FROM thread_items "
            f"WHERE item_type IN ('userMessage', 'agentMessage') ORDER BY thread_id, {order_col}"
        ))
    else:
        ids = sorted(target_ids)
        for i in range(0, len(ids), 400):
            chunk = ids[i : i + 400]
            marks = ",".join("?" * len(chunk))
            consume(conn.execute(
                f"SELECT thread_id, item_type, item_json{time_select} FROM thread_items "
                f"WHERE thread_id IN ({marks}) AND item_type IN ('userMessage', 'agentMessage') "
                f"ORDER BY thread_id, {order_col}",
                chunk,
            ))
    return out


def read_codex(codex_dir=None, state_db=None, history_db=None, sessions_dir=None, cutoff=None, now=None):
    """Read Codex 0.169+ SQLite stores and legacy rollout JSONLs."""
    s_db, h_db, sess_dir = _codex_paths(codex_dir, state_db, history_db, sessions_dir)
    threads, err = _read_sqlite(s_db, _read_codex_state)
    if err is not None:
        return [], err
    threads = threads or {}

    in_window_threads = {}
    for tid, item in threads.items():
        start = _parse_ts(item.get("created_at_ms")) or _parse_ts(item.get("created_at"))
        end = _parse_ts(item.get("updated_at_ms")) or _parse_ts(item.get("updated_at")) or start
        if start is None:
            start = end
        if end is None:
            continue
        if cutoff is not None and end < cutoff:
            continue
        in_window_threads[tid] = (item, start, end)

    target_ids = set(in_window_threads) if threads else None
    history = {}
    if h_db.is_file() and (target_ids is None or target_ids):
        history_res, h_err = _read_sqlite(h_db, lambda conn: _read_codex_history(conn, target_ids))
        if h_err is not None:
            return [], h_err
        history = history_res or {}

    rollouts_by_id = {}
    if sess_dir.is_dir():
        use_mtime_filter = now is None and cutoff is not None
        cutoff_epoch = cutoff.timestamp() - 86400 if cutoff is not None else None
        need_fallback = {tid for tid in in_window_threads if not (history.get(tid, {}).get("user_msgs") or history.get(tid, {}).get("last_agent"))}
        try:
            rollout_files = sorted(sess_dir.rglob("*.jsonl"))
        except OSError:
            rollout_files = []
        for rpath in rollout_files:
            try:
                if rpath.is_symlink() or not rpath.is_file():
                    continue
                st = rpath.stat()
            except OSError:
                continue
            # If the thread already exists in threads & has SQLite items, skip parsing its rollout JSONL.
            matched_known = next((tid for tid in threads if tid in rpath.name), None)
            if matched_known is not None and matched_known not in need_fallback:
                continue
            if use_mtime_filter and st.st_mtime < cutoff_epoch and matched_known not in need_fallback:
                continue
            parsed = _parse_codex_rollout(rpath)
            if parsed:
                parsed["_mtime"] = st.st_mtime
                rollouts_by_id[parsed["id"]] = parsed

    records = []
    for tid, (item, start, end) in in_window_threads.items():
        hist = history.get(tid, {})
        user_msgs = list(hist.get("user_msgs") or [])
        last_agent = hist.get("last_agent") or ""
        if not user_msgs and not last_agent and tid in rollouts_by_id:
            ro = rollouts_by_id[tid]
            user_msgs = list(ro["user_msgs"])
            last_agent = ro["last_agent"]
        if not user_msgs and isinstance(item.get("first_user_message"), str) and item["first_user_message"].strip():
            fmsg = _SYSTEM_REMINDER_RE.sub("", item["first_user_message"]).strip()
            if fmsg and not fmsg.startswith(_CODEX_SKIP_PREFIXES):
                user_msgs = [fmsg]
        baslik = str(item.get("name") or item.get("title") or "")
        if not user_msgs and not last_agent and not baslik.strip():
            continue
        tur = _codex_classify(item.get("thread_source"), item.get("source"), item.get("originator"))
        records.append(
            _make_record(
                "codex",
                tid,
                start,
                end,
                str(item.get("cwd") or ""),
                user_msgs,
                last_agent,
                tur,
                baslik=baslik,
            )
        )

    # Also include history-only threads if state_5.sqlite was absent
    if not threads:
        for tid, hist in history.items():
            ts_list = hist.get("timestamps") or []
            if not ts_list:
                continue
            start, end = min(ts_list), max(ts_list)
            if cutoff is not None and end < cutoff:
                continue
            records.append(
                _make_record(
                    "codex",
                    tid,
                    start,
                    end,
                    "",
                    hist.get("user_msgs") or [],
                    hist.get("last_agent") or "",
                    "kullanici",
                )
            )

    seen_ids = {r["oturum_id"] for r in records}
    for tid, ro in rollouts_by_id.items():
        if tid in seen_ids or tid in threads:
            continue
        if not ro["user_msgs"] and not ro["last_agent"]:
            continue
        ts_list = ro["timestamps"]
        if ts_list:
            start, end = min(ts_list), max(ts_list)
        else:
            fallback = datetime.fromtimestamp(ro["_mtime"], tz=timezone.utc)
            start, end = fallback, fallback
        if cutoff is not None and end < cutoff:
            continue
        tur = _codex_classify(ro.get("thread_source"), ro.get("source"), ro.get("originator"))
        records.append(
            _make_record(
                "codex",
                tid,
                start,
                end,
                ro.get("cwd") or "",
                ro["user_msgs"],
                ro["last_agent"],
                tur,
            )
        )
    return records, None


def _slice_fts_body(body_text, offsets_raw, is_user):
    if not isinstance(body_text, str) or not body_text.strip():
        return []
    if offsets_raw:
        try:
            raw_str = offsets_raw.decode("utf-8", "ignore") if isinstance(offsets_raw, (bytes, bytearray)) else str(offsets_raw)
            pairs = json.loads(raw_str)
            if isinstance(pairs, list) and pairs:
                offsets = sorted({int(p[1]) for p in pairs if isinstance(p, (list, tuple)) and len(p) >= 2 and int(p[1]) >= 0})
                if offsets:
                    encoded = body_text.encode("utf-8")
                    slices = []
                    for i, start in enumerate(offsets):
                        end = offsets[i + 1] if i + 1 < len(offsets) else len(encoded)
                        if start >= len(encoded) or end <= start:
                            continue
                        chunk = encoded[start:end].decode("utf-8", "replace").strip()
                        chunk = _SYSTEM_REMINDER_RE.sub("", chunk).strip()
                        if chunk:
                            slices.append(chunk)
                    if slices:
                        return slices
        except (ValueError, TypeError, IndexError):
            pass
    cleaned = _SYSTEM_REMINDER_RE.sub("", body_text).strip()
    if not cleaned:
        return []
    if is_user:
        return [line.strip() for line in cleaned.splitlines() if line.strip()]
    parts = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
    return parts or [cleaned]


def _read_antigravity_db(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "conversation_summaries" not in tables:
        return []
    sum_cols = _table_columns(conn, "conversation_summaries")
    wanted = ["conversation_id", "title", "step_count", "last_modified_time", "last_user_input_time",
              "workspace_uris", "nesting_depth", "agent_name", "preview"]
    selected = [c for c in wanted if c in sum_cols]
    if "conversation_id" not in selected:
        return []

    fts_by_id = {}
    if "conversations_fts_content" in tables:
        fts_cols = _table_columns(conn, "conversations_fts_content")
        fts_wanted = [c for c in ("c0", "c1", "c8", "c9", "c10", "c11", "c13", "c14") if c in fts_cols]
        if {"c0", "c13", "c14"} & set(fts_wanted) and "c0" in fts_wanted:
            order = "c0, CAST(c1 AS INTEGER) ASC" if "c1" in fts_wanted else "c0, rowid ASC"
            for row in conn.execute(f"SELECT {', '.join(fts_wanted)} FROM conversations_fts_content ORDER BY {order}"):
                item = dict(zip(fts_wanted, row))
                cid = str(item.get("c0") or "")
                if not cid:
                    continue
                bucket = fts_by_id.setdefault(cid, {"user_msgs": [], "agent_msgs": [], "title": "", "workspace": ""})
                if not bucket["title"] and isinstance(item.get("c10"), str) and item["c10"].strip():
                    bucket["title"] = item["c10"].strip()
                if not bucket["workspace"] and isinstance(item.get("c11"), str) and item["c11"].strip():
                    bucket["workspace"] = item["c11"].strip()
                bucket["user_msgs"].extend(_slice_fts_body(item.get("c13"), item.get("c8"), is_user=True))
                bucket["agent_msgs"].extend(_slice_fts_body(item.get("c14"), item.get("c9"), is_user=False))

    rows = []
    for row in conn.execute(f"SELECT {', '.join(selected)} FROM conversation_summaries"):
        item = dict(zip(selected, row))
        cid = str(item.get("conversation_id") or "")
        if cid:
            item["_fts"] = fts_by_id.get(cid, {})
            rows.append(item)
    return rows


def _parse_workspace_uris(raw_uris, fallback_ws=""):
    paths = []
    if isinstance(raw_uris, str) and raw_uris.strip():
        text = raw_uris.strip()
        if text.startswith("["):
            try:
                arr = json.loads(text)
                if isinstance(arr, list):
                    paths.extend(_uri_to_path(u) for u in arr if isinstance(u, str) and u.strip())
            except ValueError:
                paths.append(_uri_to_path(text))
        else:
            paths.append(_uri_to_path(text))
    elif isinstance(raw_uris, list):
        paths.extend(_uri_to_path(u) for u in raw_uris if isinstance(u, str) and u.strip())
    paths = [p for p in paths if p]
    if not paths and fallback_ws:
        paths = [_uri_to_path(fallback_ws)]
    return paths


def read_antigravity(antigravity_db=None, cutoff=None):
    """Read Antigravity conversations from ~/.gemini/antigravity/conversation_summaries.db."""
    db_path = _antigravity_db(antigravity_db)
    rows, err = _read_sqlite(db_path, _read_antigravity_db)
    if err is not None:
        return [], err
    if not rows:
        return [], None

    records = []
    for item in rows:
        cid = str(item["conversation_id"])
        mod_ts = _parse_ts(item.get("last_modified_time"))
        usr_ts = _parse_ts(item.get("last_user_input_time"))
        end = mod_ts or usr_ts
        if end is None:
            continue
        if usr_ts is not None and mod_ts is not None:
            start = min(usr_ts, mod_ts)
            end = max(usr_ts, mod_ts)
        else:
            start = end
        if cutoff is not None and end < cutoff:
            continue

        fts = item.get("_fts") or {}
        user_msgs = fts.get("user_msgs") or []
        agent_msgs = fts.get("agent_msgs") or []
        last_agent = agent_msgs[-1] if agent_msgs else str(item.get("preview") or "")
        title = str(item.get("title") or fts.get("title") or "")
        step_count = item.get("step_count")
        if step_count == 0 and not user_msgs and not last_agent and not title:
            continue

        workspaces = _parse_workspace_uris(item.get("workspace_uris"), fts.get("workspace", ""))
        cwd = workspaces[0] if workspaces else ""
        try:
            depth = int(item.get("nesting_depth") or 0)
        except (TypeError, ValueError):
            depth = 0
        if depth > 0:
            tur = "ic_ajan"
        elif any("-pasla-" in w.casefold() for w in workspaces):
            tur = "isci"
        else:
            tur = "kullanici"

        records.append(
            _make_record(
                "antigravity",
                cid,
                start,
                end,
                cwd,
                user_msgs,
                last_agent,
                tur,
                baslik=title,
            )
        )
    return records, None


def _companion_dir(vault):
    try:
        from beyin_v3_companion import directory
        return directory(vault)
    except ImportError:
        import importlib.util
        comp_path = Path(__file__).resolve().parent / "beyin_v3_companion.py"
        if not comp_path.is_file():
            return None
        spec = importlib.util.spec_from_file_location("beyin_v3_companion", comp_path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.directory(vault)
    except Exception:
        return None


def _vault_card_index(vault):
    """Collect 8-char alphanumeric prefixes and text haystacks from Oturumlar/ and Devir/."""
    companion = _companion_dir(vault)
    if companion is None or not companion.is_dir():
        return companion, set(), ""
    prefixes8 = set()
    texts = []
    for sub in ("Oturumlar", "Devir"):
        folder = companion / sub
        if folder.is_symlink() or not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.md")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            chunk = path.name + "\n" + content
            texts.append(chunk)
            for token in _TOKEN8_RE.findall(chunk):
                prefixes8.add(token[:8].lower())
    return companion, prefixes8, "\n".join(texts)


def _is_registered(oturum_id, prefixes8, haystack):
    raw8 = str(oturum_id or "")[:8].lower()
    if not raw8:
        return False
    hash8 = hashlib.sha256(str(oturum_id).encode("utf-8")).hexdigest()[:8]
    if hash8 in prefixes8:
        return True
    if raw8.isalnum() and len(raw8) == 8:
        return raw8 in prefixes8
    return bool(re.search(r"(?<![0-9a-zA-Z])" + re.escape(raw8), haystack, re.I))


def tara(
    vault,
    gun=DEFAULT_DAYS,
    *,
    now=None,
    state=None,
    claude_dir=None,
    codex_dir=None,
    codex_state_db=None,
    codex_history_db=None,
    codex_sessions_dir=None,
    antigravity_db=None,
):
    """Scan all three clients for the last `gun` days and cross-check vault cards (read-only)."""
    if type(gun) is not int or gun < 1:
        raise ValueError("--gun pozitif bir tam sayi olmali")
    vault_path = Path(vault).expanduser().resolve()
    if now is None:
        end_dt = datetime.now(timezone.utc)
    else:
        end_dt = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        end_dt = end_dt.astimezone(timezone.utc)
    cutoff = end_dt - timedelta(days=gun)

    no_mem = _no_memory_ids(state)
    claude_rows, claude_err = read_claude(claude_dir=claude_dir, cutoff=cutoff, now=now, no_memory_ids=no_mem)
    codex_rows, codex_err = read_codex(
        codex_dir=codex_dir,
        state_db=codex_state_db,
        history_db=codex_history_db,
        sessions_dir=codex_sessions_dir,
        cutoff=cutoff,
        now=now,
    )
    ag_rows, ag_err = read_antigravity(antigravity_db=antigravity_db, cutoff=cutoff)

    companion, prefixes8, haystack = _vault_card_index(vault_path)
    all_rows = claude_rows + codex_rows + ag_rows
    isci_kimlikleri = no_mem | _orkestrator_is_kimlikleri()
    for rec in all_rows:
        if rec["tur"] == "kullanici" and rec["oturum_id"] in isci_kimlikleri:
            rec["tur"] = "isci"
        matched = _is_registered(rec["oturum_id"], prefixes8, haystack)
        rec["kayitli"] = matched
        rec["kayitsiz"] = (rec["tur"] == "kullanici") and not matched

    all_rows.sort(key=lambda r: (r["bitis"], r["baslangic"], r["oturum_id"]), reverse=True)

    ozet = {}
    okunamayan = []
    for name, rows, err in (("claude", claude_rows, claude_err), ("codex", codex_rows, codex_err), ("antigravity", ag_rows, ag_err)):
        if err is not None:
            ozet[name] = {"durum": "okunamadı", "hata": err, "kullanici": 0, "isci": 0, "ic_ajan": 0, "kayitsiz": 0, "toplam": 0}
            okunamayan.append({"istemci": name, "hata": err})
        else:
            ozet[name] = {
                "durum": "ok",
                "kullanici": sum(1 for r in rows if r["tur"] == "kullanici"),
                "isci": sum(1 for r in rows if r["tur"] == "isci"),
                "ic_ajan": sum(1 for r in rows if r["tur"] == "ic_ajan"),
                "kayitsiz": sum(1 for r in rows if r["kayitsiz"]),
                "toplam": len(rows),
            }

    kullanici_oturumlari = [r for r in all_rows if r["tur"] == "kullanici"]
    kayitsiz_oturumlari = [r for r in kullanici_oturumlari if r["kayitsiz"]]
    companion_rel = None
    if companion is not None and companion.is_dir():
        try:
            companion_rel = companion.relative_to(vault_path).as_posix()
        except ValueError:
            companion_rel = str(companion)

    return {
        "gun": gun,
        "baslangic": cutoff.isoformat(),
        "bitis": end_dt.isoformat(),
        "companion": companion_rel,
        "ozet": ozet,
        "okunamayan": okunamayan,
        "kayitsiz_kullanici_oturumlari": kayitsiz_oturumlari,
        "kullanici_oturumlari": kullanici_oturumlari,
        "oturumlar": all_rows,
    }


def _format_session_lines(rec, include_status=False):
    when = _local_stamp(rec["bitis"])
    cwd_part = f" · `{rec['cwd']}`" if rec["cwd"] else ""
    status_part = ""
    if include_status:
        status_part = " · **kayıtsız**" if rec["kayitsiz"] else " · kayıtlı"
    title_part = f" · _{rec['baslik']}_" if rec.get("baslik") and rec["baslik"] != rec["ilk_kullanici_mesaji"] else ""
    lines = [
        f"- `{when}` · **{rec['istemci']}** · `{rec['id8']}`{status_part}{title_part}{cwd_part} ({rec['kullanici_mesaj_sayisi']} mesaj)"
    ]
    if rec["ilk_kullanici_mesaji"]:
        lines.append(f"  - ilk: {rec['ilk_kullanici_mesaji']}")
    if rec["son_kullanici_mesaji"] and rec["son_kullanici_mesaji"] != rec["ilk_kullanici_mesaji"]:
        lines.append(f"  - son: {rec['son_kullanici_mesaji']}")
    if rec["son_ajan_mesaji"]:
        lines.append(f"  - ajan: {rec['son_ajan_mesaji']}")
    return lines


def markdown_ozet(report):
    """Format scan report as readable Markdown without modifying any state."""
    lines = [f"# Sohbet taraması (son {report['gun']} gün)", "", "## İstemci özeti"]
    for name in ("claude", "codex", "antigravity"):
        info = report["ozet"].get(name, {})
        if info.get("durum") == "okunamadı":
            lines.append(f"- **{name}**: okunamadı ({info.get('hata', 'hata')})")
        else:
            lines.append(
                f"- **{name}**: {info.get('kullanici', 0)} kullanıcı, {info.get('isci', 0)} işçi, "
                f"{info.get('ic_ajan', 0)} iç ajan (kayıtsız kullanıcı: {info.get('kayitsiz', 0)})"
            )

    unreg = report.get("kayitsiz_kullanici_oturumlari", [])
    lines += ["", f"## Kayıtsız kullanıcı oturumları ({len(unreg)})"]
    if not unreg:
        lines.append("- Kayıtsız kullanıcı oturumu yok.")
    else:
        for rec in unreg:
            lines.extend(_format_session_lines(rec, include_status=False))

    users = report.get("kullanici_oturumlari", [])
    lines += ["", f"## Kullanıcı oturumları ({len(users)}, en yeni önce)"]
    if not users:
        lines.append("- Bu aralıkta kullanıcı oturumu yok.")
    else:
        for rec in users:
            lines.extend(_format_session_lines(rec, include_status=True))

    return "\n".join(lines) + "\n"
