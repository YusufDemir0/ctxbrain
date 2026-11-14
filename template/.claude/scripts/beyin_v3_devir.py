"""Devir kartı: limit ya da kesinti iş ortasında gelirse başka bir model kaldığı yerden devam edebilsin.

Sorun: oturum kartı ve receipt'i model iş sonunda yazar; limit iş ortasında dolarsa vault'ta iz kalmaz ve
sonraki istemci (Codex, Claude, ...) ham sohbet kaydını elle okumak zorunda kalır.

Çözüm: hook her istekte, her tur sonunda (Stop), API hatasıyla kesilen turda (StopFailure), sıkıştırma ve
oturum kapanışında, araç çağrılarında da en fazla dakikada bir, sohbet kaydından MODEL ÇAĞIRMADAN bir devir
kartı üretir: son istekler, görev listesi, değişen dosyalar, son asistan mesajı, kesinti nedeni, kayıt yolu.
Kart `<companion>/Devir/` altındadır; açık kartlar Last-Session.md'nin başında "Yarım kalan işler" olarak
görünür. Aynı oturumun kartı (`oturum yaz`) ya da `devir kapat` kartı kapatır (silmez, Devir/Arşiv'e taşır).

Fail open: her hata sessizce yutulur, hook turu asla düşürmez.
"""
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

TAIL_BYTES = 4_000_000       # yalnız kaydın sonu okunur; hook süre sınırını aşmasın
THROTTLE_SECONDS = 60        # PostToolUse'ta en fazla dakikada bir yazılır
MAX_REQUESTS = 5
MAX_FILES = 15
OPEN_DAYS = 7                # bu süreden eski açık kart özetlenmez
SECTION_CAP = 900            # Last-Session.md içindeki bölüm payı
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}
FORCE_EVENTS = {"UserPromptSubmit", "Stop", "StopFailure", "PreCompact", "SessionEnd"}
SKIP_USER = ("<system-reminder>", "Base directory for this skill", "<command-", "[Request interrupted",
             "Caveat:", "# AGENTS.md instructions", "<environment_context>", "<user_instructions>",
             "<INSTRUCTIONS>", "<turn_aborted>")


def sid8(session_id):
    """Receipt/oturum kartıyla aynı kimlik: sha256(session_id)'nin ilk 8 onaltılığı."""
    return hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()[:8]


def _atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".devir-", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    os.replace(tmp, path)


def _folder(vault):
    from beyin_v3_companion import directory
    target = directory(vault)
    return None if target is None else target / "Devir"


def _clip(text, n):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _tail_lines(path):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        data = f.read()
    lines = data.decode("utf-8", "ignore").splitlines()
    if size > TAIL_BYTES and lines:
        lines = lines[1:]  # ilk satır yarım olabilir
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _user_text(text):
    text = str(text).strip()
    if not text or text.startswith(SKIP_USER):
        return None
    return text


# ---------- Claude Code transcript ----------

def _plan_apply(plan, data, name):
    if name == "TodoWrite" and isinstance(data.get("todos"), list):
        return [{"content": str(t.get("content", "")), "status": str(t.get("status", "pending"))}
                for t in data["todos"] if isinstance(t, dict)]
    if isinstance(data.get("items"), list):
        return [{"content": str(t.get("content", "")), "status": str(t.get("status", "pending"))}
                for t in data["items"] if isinstance(t, dict)]
    if not plan:
        return plan
    plan = [dict(t) for t in plan]
    if data.get("advance"):
        cur = next((i for i, t in enumerate(plan) if t["status"] == "in_progress"), None)
        if cur is not None:
            plan[cur]["status"] = "completed"
        nxt = next((i for i, t in enumerate(plan) if t["status"] == "pending"), None)
        if nxt is not None:
            plan[nxt]["status"] = "in_progress"
    for n in data.get("done") or []:
        if isinstance(n, int) and 1 <= n <= len(plan):
            plan[n - 1]["status"] = "completed"
    n = data.get("start")
    if isinstance(n, int) and 1 <= n <= len(plan):
        plan[n - 1]["status"] = "in_progress"
    return plan


def parse_claude(records):
    out = {"requests": [], "plan": [], "files": [], "last_assistant": "", "commands": []}
    for d in records:
        kind = d.get("type")
        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
        content = msg.get("content")
        when = str(d.get("timestamp", ""))[:16].replace("T", " ")
        if kind == "user":
            texts = [content] if isinstance(content, str) else [
                x.get("text", "") for x in content or [] if isinstance(x, dict) and x.get("type") == "text"]
            for t in texts:
                t = _user_text(t)
                if t:
                    out["requests"].append((when, t))
        elif kind == "assistant" and isinstance(content, list):
            for x in content:
                if not isinstance(x, dict):
                    continue
                if x.get("type") == "text" and x.get("text", "").strip():
                    out["last_assistant"] = x["text"]
                elif x.get("type") == "tool_use":
                    name, data = str(x.get("name", "")), x.get("input") if isinstance(x.get("input"), dict) else {}
                    if name.endswith("update_plan") or name == "TodoWrite":
                        out["plan"] = _plan_apply(out["plan"], data, name)
                    elif name.endswith("wrap_up"):  # tur kapanışı görev listesini tamamlar
                        out["plan"] = [dict(t, status="completed") for t in out["plan"]]
                    elif name in EDIT_TOOLS:
                        p = data.get("file_path") or data.get("notebook_path")
                        if isinstance(p, str):
                            out["files"].append(p)
                    elif name == "Bash" and isinstance(data.get("command"), str):
                        out["commands"].append(data.get("description") or data["command"])
    return out


# ---------- Codex rollout ----------

PATCH_FILE = re.compile(r"\*\*\* (?:Update|Add|Delete) File: ([^\n\\\"]+)")
CODEX_STEP = re.compile(r"[\"']?step[\"']?\s*:\s*[\"']([^\"']+)[\"']\s*,\s*[\"']?status[\"']?\s*:\s*[\"'](\w+)[\"']")


def _unescape(text):
    try:
        return json.loads('"' + text.replace('"', '\\"') + '"')
    except ValueError:
        return text


def parse_codex(records):
    out = {"requests": [], "plan": [], "files": [], "last_assistant": "", "commands": []}
    for d in records:
        p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
        when = str(d.get("timestamp", ""))[:16].replace("T", " ")
        if d.get("type") == "event_msg" and p.get("type") == "task_complete" and p.get("last_agent_message"):
            out["last_assistant"] = str(p["last_agent_message"])
        if d.get("type") != "response_item":
            continue
        kind = p.get("type")
        if kind == "message":
            texts = [x.get("text", "") for x in p.get("content") or [] if isinstance(x, dict)]
            if p.get("role") == "user":
                for t in texts:
                    t = _user_text(t)
                    if t:
                        out["requests"].append((when, t))
            elif p.get("role") == "assistant" and any(t.strip() for t in texts):
                out["last_assistant"] = " ".join(t for t in texts if t.strip())
        elif kind in ("function_call", "custom_tool_call"):
            body = str(p.get("arguments") or p.get("input") or "")
            out["files"] += [f.strip() for f in PATCH_FILE.findall(body)]
            if "update_plan" in str(p.get("name")) or "update_plan" in body:
                plan = None
                try:
                    args = json.loads(body)
                    if isinstance(args, dict) and isinstance(args.get("plan"), list):
                        plan = [{"content": str(t.get("step", "")), "status": str(t.get("status", "pending"))}
                                for t in args["plan"] if isinstance(t, dict)]
                except ValueError:
                    pass
                if plan is None:
                    plan = [{"content": _unescape(st), "status": stat} for st, stat in CODEX_STEP.findall(body)]
                if plan:
                    out["plan"] = plan
            m = re.search(r"cmd\s*:\s*\"([^\"]{1,200})", body)
            if m:
                out["commands"].append(m.group(1))
    return out


def _codex_transcript(session_id):
    base = Path.home() / ".codex" / "sessions"
    if not base.is_dir() or not session_id:
        return None
    hits = sorted(base.glob(f"*/*/*/rollout-*{session_id}*.jsonl"), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def transcript_of(harness, payload):
    path = payload.get("transcript_path")
    if isinstance(path, str) and path and Path(path).is_file():
        return Path(path)
    if harness == "codex":
        return _codex_transcript(str(payload.get("session_id") or ""))
    return None


def parse(harness, path):
    records = _tail_lines(path)
    if harness == "codex" or any(r.get("type") == "response_item" for r in records[:50]):
        return parse_codex(records)
    return parse_claude(records)


# ---------- kart ----------

MARK = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}
DURUM_LINE = re.compile(r"^Durum: (\S+)", re.M)


def render(harness, sid, info, event, error, project, transcript, now):
    plan = info["plan"]
    done = sum(1 for t in plan if t["status"] == "completed")
    if event == "StopFailure":
        hal = f"kesildi ({error or 'API hatası'})"
    elif event == "SessionEnd":
        hal = "oturum kapandı"
    elif event == "Stop":
        hal = "tur bitti"
    else:
        hal = "çalışıyor"
    lines = [f"## Devir · {harness} · {sid}",
             f"Durum: açık · {hal} · güncellendi {now:%Y-%m-%d %H:%M}"]
    if project:
        lines.append(f"Proje: {project}")
    if transcript:
        lines.append(f"Kayıt: `{transcript}`")
    if info["requests"]:
        lines += ["", "### Son istekler"]
        lines += [f"- {w} · {_clip(t, 400)}" for w, t in info["requests"][-MAX_REQUESTS:]]
    if plan:
        lines += ["", f"### Görev listesi ({done}/{len(plan)})"]
        lines += [f"- {MARK.get(t['status'], '[ ]')} {_clip(t['content'], 160)}" for t in plan]
    files = list(dict.fromkeys(reversed(info["files"])))[:MAX_FILES]
    if files:
        lines += ["", "### Değişen dosyalar"] + [f"- `{f}`" for f in files]
    if info["commands"]:
        lines += ["", "### Son komutlar"] + [f"- {_clip(c, 160)}" for c in info["commands"][-4:]]
    if info["last_assistant"]:
        lines += ["", "### Son asistan mesajı", "> " + _clip(info["last_assistant"], 900)]
    lines += ["", "### Devralan için",
              f"`beyin.py devir goster {sid} --detay` sohbetin son turlarını düz metin verir. İşi bitirince kendi "
              f"oturum kartını yaz; ardından `beyin.py devir kapat {sid}` (aynı oturum `oturum yaz` derse kendiliğinden kapanır)."]
    return "\n".join(lines) + "\n"


def _card_path(folder, harness, sid):
    return folder / f"{sid}-{harness}.md"


def guncelle(vault, state, harness, payload, event, project=None, now=None):
    """Hook'tan çağrılır. Yazdıysa kart yolunu, atladıysa None döndürür. Hata yükseltmez."""
    try:
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id or session_id == "unknown":
            return None
        if os.environ.get("BEYIN_V3_NO_DEVIR") == "1":
            return None
        folder = _folder(vault)
        if folder is None:
            return None
        sid = sid8(session_id)
        stamp = Path(state) / "devir" / (sid + "-" + harness + ".json")
        t = time.time()
        if event not in FORCE_EVENTS and stamp.exists():
            try:
                if t - float(json.loads(stamp.read_text(encoding="utf-8")).get("at", 0)) < THROTTLE_SECONDS:
                    return None
            except (OSError, ValueError, TypeError):
                pass
        path = transcript_of(harness, payload)
        if path is None:
            return None
        info = parse(harness, path)
        if not (info["requests"] or info["plan"] or info["files"]):
            return None
        if event == "Stop" and isinstance(payload.get("last_assistant_message"), str):
            info["last_assistant"] = payload["last_assistant_message"]
        error = payload.get("error") or payload.get("error_details")
        now = now or datetime.now().astimezone()
        text = render(harness, sid, info, event, str(error) if error else "", project, path, now)
        try:
            from beyin_v3_secrets import redact
            cleaned = redact(text, state)
            text = cleaned[0] if isinstance(cleaned, tuple) else cleaned
        except Exception:
            pass
        card = _card_path(folder, harness, sid)
        first = not card.exists()
        _atomic(card, text)
        _atomic(stamp, json.dumps({"at": t}))
        if first or event in FORCE_EVENTS:
            try:
                from beyin_v3_oturum import derle
                derle(vault, state)
            except Exception:
                pass
        return card
    except Exception:
        if os.environ.get("BEYIN_V3_DEVIR_DEBUG") == "1":
            import traceback
            traceback.print_exc()
        return None


def acik(vault, now=None):
    """Açık devir kartları, en yeni önce."""
    folder = _folder(vault)
    if folder is None or not folder.is_dir():
        return []
    now = now or time.time()
    out = []
    for p in folder.glob("*.md"):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        m = DURUM_LINE.search(text)
        if not m or m.group(1) != "açık" or now - p.stat().st_mtime > OPEN_DAYS * 86400:
            continue
        out.append({"path": p, "sid": p.name.split("-", 1)[0], "text": text, "mtime": p.stat().st_mtime})
    return sorted(out, key=lambda c: c["mtime"], reverse=True)


def yarim(text):
    """Özette gösterilecek mi: kesilen tur ya da bitmemiş görev listesi. Normal biten oturum gürültü yapmasın."""
    lines = text.splitlines()
    if len(lines) > 1 and "kesildi" in lines[1]:
        return True
    m = re.search(r"^### Görev listesi \((\d+)/(\d+)\)", text, re.M)
    return bool(m and int(m.group(1)) < int(m.group(2)))


def ozet(vault, exclude_sid=None):
    """Last-Session.md için kısa bölüm; açık kart yoksa ''."""
    items = [c for c in acik(vault) if c["sid"] != exclude_sid and yarim(c["text"])]
    if not items:
        return ""
    rows = []
    for c in items[:3]:
        t = c["text"]
        head = t.splitlines()[0].replace("## Devir · ", "")
        lines = t.splitlines()
        durum = lines[1].replace("Durum: açık · ", "") if len(lines) > 1 else ""
        proje = re.search(r"^Proje: (.+)$", t, re.M)
        istek = re.findall(r"^- \d{4}-\d\d-\d\d \d\d:\d\d · (.+)$", t, re.M)
        gorev = re.search(r"^### Görev listesi \((\d+/\d+)\)", t, re.M)
        satir = f"- **{head}** · {durum}"
        if proje:
            satir += f" · {proje.group(1)}"
        if gorev:
            satir += f" · görev {gorev.group(1)}"
        if istek:
            satir += f"\n  son istek: {_clip(istek[-1], 160)}"
        satir += f"\n  → `beyin.py devir goster {c['sid']}` (`Devir/{c['path'].name}`)"
        rows.append(satir)
    text = "## Yarım kalan işler (devir)\n" + "\n".join(rows) + "\n"
    while len(text) > SECTION_CAP and len(rows) > 1:
        rows.pop()
        text = "## Yarım kalan işler (devir)\n" + "\n".join(rows) + "\n"
    return text[:SECTION_CAP]


def kapat(vault, sid, sebep="kapatıldı"):
    """Kartı silmeden Devir/Arşiv'e taşır; kapatılan kart sayısını döndürür."""
    folder = _folder(vault)
    if folder is None or not folder.is_dir():
        return 0
    sid = re.sub(r"[^0-9a-f]", "", str(sid).lower())[:8]
    if len(sid) != 8:
        return 0
    count = 0
    for p in folder.glob(sid + "-*.md"):
        text = p.read_text(encoding="utf-8")
        text = text.replace("Durum: açık ·", f"Durum: kapandı ({sebep}, {datetime.now():%Y-%m-%d %H:%M}) ·", 1)
        target = folder / "Arşiv" / p.name
        _atomic(target, text)
        p.unlink()
        count += 1
    return count


def liste(vault):
    return [f"{datetime.fromtimestamp(c['mtime']):%Y-%m-%d %H:%M} · {c['text'].splitlines()[0].replace('## Devir · ', '')} · "
            f"{c['text'].splitlines()[1].replace('Durum: ', '')}" for c in acik(vault)]


def goster(vault, sid, detay=False, tur=12):
    folder = _folder(vault)
    sid = re.sub(r"[^0-9a-f]", "", str(sid).lower())[:8]
    cards = sorted(folder.glob(sid + "-*.md")) if folder and folder.is_dir() else []
    if not cards:
        cards = sorted((folder / "Arşiv").glob(sid + "-*.md")) if folder and (folder / "Arşiv").is_dir() else []
    if not cards:
        raise ValueError(f"{sid} için devir kartı yok")
    text = cards[0].read_text(encoding="utf-8")
    if not detay:
        return text
    m = re.search(r"^Kayıt: `(.+)`$", text, re.M)
    path = Path(m.group(1)) if m else None
    if path is None or not path.is_file():
        return text + "\n(Sohbet kaydı bu makinede yok; yalnız kart gösterildi.)\n"
    return text + "\n## Sohbetin son turları\n" + "\n".join(turlar(path, tur)) + "\n"


def turlar(path, n=12):
    """Kayıttan son n kullanıcı/asistan metni (araç çıktıları ve sistem eklentileri hariç)."""
    out = []
    for d in _tail_lines(path):
        if d.get("type") in ("user", "assistant"):
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            c = msg.get("content")
            texts = [c] if isinstance(c, str) else [x.get("text", "") for x in c or []
                                                       if isinstance(x, dict) and x.get("type") == "text"]
            for t in texts:
                t = _user_text(t) if d["type"] == "user" else str(t).strip()
                if t:
                    out.append(("Kullanıcı" if d["type"] == "user" else "Asistan", t))
        elif d.get("type") == "response_item" and (d.get("payload") or {}).get("type") == "message":
            p = d["payload"]
            for x in p.get("content") or []:
                t = x.get("text", "") if isinstance(x, dict) else ""
                t = _user_text(t) if p.get("role") == "user" else str(t).strip()
                if t and p.get("role") in ("user", "assistant"):
                    out.append(("Kullanıcı" if p["role"] == "user" else "Asistan", t))
    return [f"\n**{who}:** {_clip(t, 1500)}" for who, t in out[-n:]]
