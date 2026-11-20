"""Synthetic tests for cross-client sohbetler scanning, classification, vault matching and SQLite locking."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from v3_package_helpers import ROOT, install, isolated_env, run_python, snapshot

SCRIPTS = ROOT / "template/.claude/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import beyin_v3_devir as devir  # noqa: E402
import beyin_v3_oturum as oturum  # noqa: E402
import beyin_v3_sohbetler as sohbetler  # noqa: E402

NOW = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)


def iso(days_ago=0, hours_ago=0):
    return (NOW - timedelta(days=days_ago, hours=hours_ago)).isoformat().replace("+00:00", "Z")


def unix_sec(days_ago=0, hours_ago=0):
    return int((NOW - timedelta(days=days_ago, hours=hours_ago)).timestamp())


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def build_claude_fixtures(claude_dir):
    # 1. User session with <system-reminder>, tool_result, isMeta, list content, mixed sidechain line
    write_jsonl(
        claude_dir / "-home-u-proj" / "1111aaaa-0000-0000-0000-000000000001.jsonl",
        [
            {"type": "user", "sessionId": "1111aaaa-0000-0000-0000-000000000001", "cwd": "/home/u/proj",
             "entrypoint": "claude-desktop", "isSidechain": False, "isMeta": True, "timestamp": iso(1, 3),
             "message": {"role": "user", "content": "meta talimatı"}},
            {"type": "user", "sessionId": "1111aaaa-0000-0000-0000-000000000001", "cwd": "/home/u/proj",
             "entrypoint": "claude-desktop", "isSidechain": False, "timestamp": iso(1, 2),
             "message": {"role": "user", "content": "<system-reminder>gizli bağlam</system-reminder> İlk kullanıcı mesajı"}},
            {"type": "assistant", "sessionId": "1111aaaa-0000-0000-0000-000000000001", "isSidechain": False,
             "timestamp": iso(1, 2),
             "message": {"role": "assistant", "content": [
                 {"type": "thinking", "thinking": "iç düşünce"},
                 {"type": "tool_use", "name": "Read", "input": {"file_path": "a.py"}},
                 {"type": "text", "text": "Ara yanıt"},
             ]}},
            {"type": "user", "sessionId": "1111aaaa-0000-0000-0000-000000000001", "isSidechain": False,
             "timestamp": iso(1, 2),
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
            {"type": "user", "sessionId": "1111aaaa-0000-0000-0000-000000000001", "isSidechain": True,
             "timestamp": iso(1, 2),
             "message": {"role": "user", "content": "yan dal iç mesajı"}},
            {"type": "user", "sessionId": "1111aaaa-0000-0000-0000-000000000001", "isSidechain": False,
             "timestamp": iso(1, 1),
             "message": {"role": "user", "content": [
                 {"type": "text", "text": "<system-reminder>ek</system-reminder>\nSon kullanıcı sorusu"}]}},
            {"type": "assistant", "sessionId": "1111aaaa-0000-0000-0000-000000000001", "isSidechain": False,
             "timestamp": iso(1, 0),
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Son Claude cevabı"}]}},
        ],
    )
    # 2. Claude worker (claude -p / sdk-cli)
    write_jsonl(
        claude_dir / "-home-u-proj" / "2222bbbb-0000-0000-0000-000000000002.jsonl",
        [
            {"type": "user", "sessionId": "2222bbbb-0000-0000-0000-000000000002", "cwd": "/home/u/proj-pasla-1",
             "entrypoint": "sdk-cli", "isSidechain": False, "timestamp": iso(2, 1),
             "message": {"role": "user", "content": "İşçi görevi yap"}},
            {"type": "assistant", "sessionId": "2222bbbb-0000-0000-0000-000000000002", "isSidechain": False,
             "timestamp": iso(2, 0),
             "message": {"role": "assistant", "content": "İşçi tamamladı"}},
        ],
    )
    # 3. Claude internal subagent (subagents/ + isSidechain=True)
    write_jsonl(
        claude_dir / "-home-u-proj" / "1111aaaa-0000-0000-0000-000000000001" / "subagents" / "agent-sub00001.jsonl",
        [
            {"type": "user", "sessionId": "1111aaaa-0000-0000-0000-000000000001", "agentId": "agent-sub00001",
             "cwd": "/home/u/proj", "isSidechain": True, "timestamp": iso(1, 1),
             "message": {"role": "user", "content": "Alt ajan araması"}},
            {"type": "assistant", "sessionId": "1111aaaa-0000-0000-0000-000000000001", "agentId": "agent-sub00001",
             "isSidechain": True, "timestamp": iso(1, 1),
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Alt ajan sonucu"}]}},
        ],
    )
    # 4. Old Claude session outside 10-day window
    write_jsonl(
        claude_dir / "-home-u-proj" / "9999old0-0000-0000-0000-000000000009.jsonl",
        [
            {"type": "user", "sessionId": "9999old0-0000-0000-0000-000000000009", "cwd": "/home/u/proj",
             "isSidechain": False, "timestamp": iso(15, 0),
             "message": {"role": "user", "content": "Çok eski sohbet"}},
        ],
    )


def build_codex_fixtures(codex_dir):
    codex_dir.mkdir(parents=True, exist_ok=True)
    state_db = codex_dir / "state_5.sqlite"
    hist_db = codex_dir / "thread_history_1.sqlite"
    sessions_dir = codex_dir / "sessions" / "2026" / "11" / "19"

    with closing(sqlite3.connect(state_db)) as db, db:
        db.execute("""
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                name TEXT,
                thread_source TEXT,
                source TEXT NOT NULL,
                model TEXT
            )
        """)
        # 1. User thread (0.169+ style: rollout has only session_meta)
        db.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)",
            ("01a10001-0000-7000-8000-000000000001", unix_sec(0, 5), unix_sec(0, 2),
             "/home/u/video", "Emre videosu", None, "user", "vscode", "gpt-5.4"),
        )
        # 2. Pasla worker (empty thread_source + source='vscode')
        db.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)",
            ("01a10002-0000-7000-8000-000000000002", unix_sec(1, 5), unix_sec(1, 4),
             "/home/u/repo-pasla-1", "Pasla işçisi", None, None, "vscode", "gpt-5.4"),
        )
        # 3. Internal subagent + guardian_review
        db.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)",
            ("01a10003-0000-7000-8000-000000000003", unix_sec(1, 3), unix_sec(1, 2),
             "/home/u/video", "Alt ajan", None, "subagent", '{"subagent":{}}', "gpt-5.4"),
        )
        db.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)",
            ("01a10004-0000-7000-8000-000000000004", unix_sec(1, 1), unix_sec(1, 0),
             "/home/u/video", "Guardian", None, "guardian_review", '{"subagent":{"other":"guardian"}}', "gpt-5.4"),
        )

    with closing(sqlite3.connect(hist_db)) as db, db:
        db.execute("""
            CREATE TABLE thread_items (
                thread_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                rollout_ordinal INTEGER NOT NULL,
                created_at_ms INTEGER NOT NULL,
                item_json TEXT NOT NULL,
                item_type TEXT NOT NULL
            )
        """)
        db.execute(
            "INSERT INTO thread_items VALUES (?,?,?,?,?,?,?)",
            ("01a10001-0000-7000-8000-000000000001", "t1", "i1", 1, unix_sec(0, 5) * 1000,
             json.dumps({"type": "userMessage", "content": [{"type": "text", "text": "Kurguyu başlat"}]}),
             "userMessage"),
        )
        db.execute(
            "INSERT INTO thread_items VALUES (?,?,?,?,?,?,?)",
            ("01a10001-0000-7000-8000-000000000001", "t2", "i2", 2, unix_sec(0, 3) * 1000,
             json.dumps({"type": "userMessage", "content": [{"type": "text", "text": "Ses seviyesini aç"}]}),
             "userMessage"),
        )
        db.execute(
            "INSERT INTO thread_items VALUES (?,?,?,?,?,?,?)",
            ("01a10001-0000-7000-8000-000000000001", "t2", "i3", 3, unix_sec(0, 2) * 1000,
             json.dumps({"type": "agentMessage", "text": "Ses seviyesi ayarlandı."}),
             "agentMessage"),
        )
        db.execute(
            "INSERT INTO thread_items VALUES (?,?,?,?,?,?,?)",
            ("01a10002-0000-7000-8000-000000000002", "t1", "i1", 1, unix_sec(1, 5) * 1000,
             json.dumps({"type": "userMessage", "content": [{"type": "text", "text": "Pasla görevi"}]}),
             "userMessage"),
        )

    # 0.169+ session_meta-only rollout for thread 01a10001
    write_jsonl(
        sessions_dir / "rollout-2026-11-20-01a10001-0000-7000-8000-000000000001.jsonl",
        [{"type": "session_meta", "timestamp": iso(0, 5),
          "payload": {"id": "01a10001-0000-7000-8000-000000000001", "cwd": "/home/u/video",
                      "thread_source": "user", "source": "vscode"}}],
    )
    # 5. Legacy Codex rollout (no state_5 row) using event_msg user_message / agent_message (also response_item for devir)
    write_jsonl(
        sessions_dir / "rollout-2026-11-17-legacy01-0000-7000-8000-000000000005.jsonl",
        [
            {"type": "session_meta", "timestamp": iso(3, 2),
             "payload": {"id": "legacy01-0000-7000-8000-000000000005", "cwd": "/home/u/eski", "source": "cli"}},
            {"type": "event_msg", "timestamp": iso(3, 2),
             "payload": {"type": "user_message", "message": "Eski sürüm kullanıcı isteği"}},
            {"type": "event_msg", "timestamp": iso(3, 1),
             "payload": {"type": "agent_message", "message": "Eski sürüm ajan yanıtı"}},
            {"type": "response_item", "timestamp": iso(3, 2),
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": "Eski sürüm kullanıcı isteği"}]}},
        ],
    )


def build_antigravity_fixtures(ag_db):
    ag_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(ag_db)) as db, db:
        db.execute("""
            CREATE TABLE conversation_summaries (
                conversation_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                step_count INTEGER NOT NULL DEFAULT 0,
                last_modified_time TEXT NOT NULL,
                last_user_input_time TEXT NOT NULL DEFAULT '',
                workspace_uris TEXT NOT NULL DEFAULT '',
                nesting_depth INTEGER NOT NULL DEFAULT 0,
                agent_name TEXT NOT NULL DEFAULT ''
            )
        """)
        db.execute("""
            CREATE TABLE conversations_fts_content (
                id INTEGER PRIMARY KEY,
                c0 TEXT,
                c1 INTEGER,
                c8 BLOB,
                c9 BLOB,
                c10 TEXT,
                c13 TEXT,
                c14 TEXT
            )
        """)
        # 1. User session (multi-chunk, byte offsets, 9-digit nanosecond stamp)
        u_id = "aguser01-0000-4000-8000-000000000001"
        db.execute(
            "INSERT INTO conversation_summaries VALUES (?,?,?,?,?,?,?,?)",
            (u_id, "Ermay sevkiyat", 12,
             "2026-11-19 18:44:43.417771568+00:00", "2026-11-19 18:10:00.100000000+00:00",
             json.dumps(["file:///home/u/ermay"]), 0, ""),
        )
        msg1, msg2 = "İlk Ermay sorusu", "İkinci Ermay sorusu"
        c13_0 = f"{msg1}\n{msg2}"
        off2 = len((msg1 + "\n").encode("utf-8"))
        c8_0 = json.dumps([[0, 0], [3, off2]]).encode("utf-8")
        c14_0 = "İlk cevap\nAra Ermay cevabı"
        c9_0 = json.dumps([[1, 0], [4, len("İlk cevap\n".encode("utf-8"))]]).encode("utf-8")
        db.execute(
            "INSERT INTO conversations_fts_content(c0,c1,c8,c9,c10,c13,c14) VALUES (?,?,?,?,?,?,?)",
            (u_id, 0, c8_0, c9_0, "Ermay sevkiyat", c13_0, c14_0),
        )
        # Second chunk (c1=1) adds final user and agent message
        db.execute(
            "INSERT INTO conversations_fts_content(c0,c1,c8,c9,c10,c13,c14) VALUES (?,?,?,?,?,?,?)",
            (u_id, 1, json.dumps([[10, 0]]).encode("utf-8"), json.dumps([[11, 0]]).encode("utf-8"),
             "Ermay sevkiyat", "Üçüncü Ermay sorusu", "Son Ermay cevabı"),
        )
        # 2. Pasla worker (-pasla- in workspace_uris)
        w_id = "agwork02-0000-4000-8000-000000000002"
        db.execute(
            "INSERT INTO conversation_summaries VALUES (?,?,?,?,?,?,?,?)",
            (w_id, "Pasla worker", 5,
             "2026-11-19 10:00:00+00:00", "0001-01-01 00:00:00+00:00",
             json.dumps(["file:///home/u/proje-pasla-gorev"]), 0, ""),
        )
        db.execute(
            "INSERT INTO conversations_fts_content(c0,c1,c8,c9,c10,c13,c14) VALUES (?,?,?,?,?,?,?)",
            (w_id, 0, None, None, "Pasla worker", "Pasla komutunu çalıştır", "Tamamlandı"),
        )
        # 3. Subagent (nesting_depth > 0)
        s_id = "agsub003-0000-4000-8000-000000000003"
        db.execute(
            "INSERT INTO conversation_summaries VALUES (?,?,?,?,?,?,?,?)",
            (s_id, "Alt araştırma", 4,
             "2026-11-19 11:00:00+00:00", "2026-11-19 10:55:00+00:00",
             json.dumps(["file:///home/u/ermay"]), 1, "research"),
        )


class SohbetlerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v5-sohbetler-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.state = self.root / "state"
        (self.vault / "🔮 850-Companion").mkdir(parents=True)
        self.claude_dir = self.root / "claude_projects"
        self.codex_dir = self.root / "codex_home"
        self.ag_db = self.root / "antigravity" / "conversation_summaries.db"

    def test_classification_filtering_and_unregistered_marking(self):
        build_claude_fixtures(self.claude_dir)
        build_codex_fixtures(self.codex_dir)
        build_antigravity_fixtures(self.ag_db)

        # Register Claude 1111aaaa via Oturumlar card (first 8 chars) and Codex legacy01 via Devir card (sha256[:8])
        oturum.yaz(self.vault, None, "1111aaaa", "claude-is", "- tamamlandı", proje="proj")
        card = devir.guncelle(
            self.vault,
            self.state,
            "codex",
            {"session_id": "legacy01-0000-7000-8000-000000000005",
             "transcript_path": str(self.codex_dir / "sessions/2026/11/19/rollout-2026-11-17-legacy01-0000-7000-8000-000000000005.jsonl")},
            "Stop",
        )
        self.assertIsNotNone(card)

        report = sohbetler.tara(
            self.vault,
            gun=10,
            now=NOW,
            state=self.state,
            claude_dir=self.claude_dir,
            codex_dir=self.codex_dir,
            antigravity_db=self.ag_db,
        )

        self.assertEqual(report["ozet"]["claude"],
                         {"durum": "ok", "kullanici": 1, "isci": 1, "ic_ajan": 1, "kayitsiz": 0, "toplam": 3})
        self.assertEqual(report["ozet"]["codex"],
                         {"durum": "ok", "kullanici": 2, "isci": 1, "ic_ajan": 2, "kayitsiz": 1, "toplam": 5})
        self.assertEqual(report["ozet"]["antigravity"],
                         {"durum": "ok", "kullanici": 1, "isci": 1, "ic_ajan": 1, "kayitsiz": 1, "toplam": 3})

        by_id = {r["oturum_id"]: r for r in report["oturumlar"]}
        # Claude user session assertions: system-reminder stripped, tool_result, isMeta, and sidechain excluded
        cl = by_id["1111aaaa-0000-0000-0000-000000000001"]
        self.assertEqual(cl["tur"], "kullanici")
        self.assertEqual(cl["kullanici_mesaj_sayisi"], 2)
        self.assertEqual(cl["ilk_kullanici_mesaji"], "İlk kullanıcı mesajı")
        self.assertEqual(cl["son_kullanici_mesaji"], "Son kullanıcı sorusu")
        self.assertEqual(cl["son_ajan_mesaji"], "Son Claude cevabı")
        self.assertNotIn("gizli bağlam", cl["ilk_kullanici_mesaji"])
        self.assertFalse(cl["kayitsiz"])
        self.assertNotIn("9999old0-0000-0000-0000-000000000009", by_id)  # >10 days excluded

        # Codex 0.169+ user thread + old rollout
        cx = by_id["01a10001-0000-7000-8000-000000000001"]
        self.assertEqual(cx["tur"], "kullanici")
        self.assertEqual(cx["kullanici_mesaj_sayisi"], 2)
        self.assertEqual(cx["ilk_kullanici_mesaji"], "Kurguyu başlat")
        self.assertEqual(cx["son_kullanici_mesaji"], "Ses seviyesini aç")
        self.assertEqual(cx["son_ajan_mesaji"], "Ses seviyesi ayarlandı.")
        self.assertTrue(cx["kayitsiz"])

        leg = by_id["legacy01-0000-7000-8000-000000000005"]
        self.assertEqual(leg["tur"], "kullanici")
        self.assertEqual(leg["ilk_kullanici_mesaji"], "Eski sürüm kullanıcı isteği")
        self.assertEqual(leg["son_ajan_mesaji"], "Eski sürüm ajan yanıtı")
        self.assertFalse(leg["kayitsiz"])  # matched Devir card via sha256[:8]

        # Antigravity multi-chunk + byte-offset UTF-8 slicing + workspace decoding + types
        ag = by_id["aguser01-0000-4000-8000-000000000001"]
        self.assertEqual(ag["tur"], "kullanici")
        self.assertEqual(ag["cwd"], "/home/u/ermay")
        self.assertEqual(ag["kullanici_mesaj_sayisi"], 3)
        self.assertEqual(ag["ilk_kullanici_mesaji"], "İlk Ermay sorusu")
        self.assertEqual(ag["son_kullanici_mesaji"], "Üçüncü Ermay sorusu")
        self.assertEqual(ag["son_ajan_mesaji"], "Son Ermay cevabı")
        self.assertTrue(ag["kayitsiz"])
        self.assertEqual(by_id["agwork02-0000-4000-8000-000000000002"]["tur"], "isci")
        self.assertFalse(by_id["agwork02-0000-4000-8000-000000000002"]["kayitsiz"])
        self.assertEqual(by_id["agsub003-0000-4000-8000-000000000003"]["tur"], "ic_ajan")

        # Markdown summary includes counts, unregistered list, and ordered user sessions
        md = sohbetler.markdown_ozet(report)
        self.assertIn("Kayıtsız kullanıcı oturumları (2)", md)
        self.assertIn("01a10001", md)
        self.assertIn("aguser01", md)
        self.assertLess(md.index("01a10001"), md.index("aguser01"))

    def test_old_codex_rollout_pure_event_msg_and_response_item_fallback(self):
        # Pure event_msg rollout (no SQLite DBs at all) + pure response_item rollout
        sessions = self.codex_dir / "sessions" / "2026" / "11" / "18"
        write_jsonl(
            sessions / "rollout-ev.jsonl",
            [
                {"type": "session_meta", "timestamp": iso(1, 0),
                 "payload": {"id": "oldcodex-1111-2222-3333-444444444444", "cwd": "/home/u/a", "source": "cli"}},
                {"type": "event_msg", "timestamp": iso(1, 0),
                 "payload": {"type": "user_message", "message": "Event msg sorusu"}},
                {"type": "event_msg", "timestamp": iso(1, 0),
                 "payload": {"type": "agent_message", "message": "Event msg yanıtı"}},
            ],
        )
        write_jsonl(
            sessions / "rollout-resp.jsonl",
            [
                {"type": "session_meta", "timestamp": iso(2, 0),
                 "payload": {"id": "respitem-1111-2222-3333-444444444444", "cwd": "/home/u/b", "source": "cli"}},
                {"type": "response_item", "timestamp": iso(2, 0),
                 "payload": {"type": "message", "role": "user",
                             "content": [{"type": "input_text", "text": "# AGENTS.md instructions for /home/u/b"}]}},
                {"type": "response_item", "timestamp": iso(2, 0),
                 "payload": {"type": "message", "role": "user",
                             "content": [{"type": "input_text", "text": "Response item sorusu"}]}},
                {"type": "response_item", "timestamp": iso(2, 0),
                 "payload": {"type": "message", "role": "assistant",
                             "content": [{"type": "output_text", "text": "Response item yanıtı"}]}},
            ],
        )
        report = sohbetler.tara(
            self.vault, gun=10, now=NOW,
            claude_dir=self.root / "yok1", codex_dir=self.codex_dir, antigravity_db=self.root / "yok3",
        )
        by_id = {r["oturum_id"]: r for r in report["oturumlar"]}
        self.assertEqual(by_id["oldcodex-1111-2222-3333-444444444444"]["ilk_kullanici_mesaji"], "Event msg sorusu")
        self.assertEqual(by_id["oldcodex-1111-2222-3333-444444444444"]["son_ajan_mesaji"], "Event msg yanıtı")
        self.assertEqual(by_id["respitem-1111-2222-3333-444444444444"]["kullanici_mesaj_sayisi"], 1)
        self.assertEqual(by_id["respitem-1111-2222-3333-444444444444"]["ilk_kullanici_mesaji"], "Response item sorusu")
        self.assertEqual(by_id["respitem-1111-2222-3333-444444444444"]["son_ajan_mesaji"], "Response item yanıtı")

    def test_custom_companion_folder_and_env_overrides(self):
        custom_vault = self.root / "custom_vault"
        partner = custom_vault / "Benim Ortağım"
        (partner / "Oturumlar").mkdir(parents=True)
        (partner / "Core.md").write_text("# Kimlik\n", encoding="utf-8")
        (partner / "Oturumlar" / "2026-11-19-1200-aguser01-ermay.md").write_text(
            "## 2026-11-19 12:00 · ermay · aguser01\n- tamam\n", encoding="utf-8"
        )
        build_antigravity_fixtures(self.ag_db)
        build_claude_fixtures(self.claude_dir)
        with patch.dict(os.environ, {
            "BEYIN_SOHBETLER_CLAUDE_DIR": str(self.claude_dir),
            "BEYIN_SOHBETLER_CODEX_DIR": str(self.root / "yok2"),
            "BEYIN_SOHBETLER_ANTIGRAVITY_DB": str(self.ag_db),
        }):
            report = sohbetler.tara(custom_vault, gun=10, now=NOW)
        self.assertEqual(report["companion"], "Benim Ortağım")
        self.assertEqual(report["ozet"]["antigravity"]["kayitsiz"], 0)
        self.assertEqual(report["ozet"]["claude"]["kullanici"], 1)

    def test_missing_sources_return_empty_silently_and_invalid_gun_rejected(self):
        report = sohbetler.tara(
            self.vault,
            gun=10,
            now=NOW,
            claude_dir=self.root / "missing_claude",
            codex_dir=self.root / "missing_codex",
            antigravity_db=self.root / "missing.db",
        )
        self.assertEqual(report["oturumlar"], [])
        self.assertEqual(report["okunamayan"], [])
        for client in ("claude", "codex", "antigravity"):
            self.assertEqual(report["ozet"][client]["durum"], "ok")
            self.assertEqual(report["ozet"][client]["toplam"], 0)
        with self.assertRaises(ValueError):
            sohbetler.tara(self.vault, gun=0, now=NOW)

    def test_locked_sqlite_falls_back_to_temp_copy_and_unreadable_reports_okunamadi(self):
        build_antigravity_fixtures(self.ag_db)
        # Hold an exclusive write lock on Antigravity DB so direct ?mode=ro fails with database is locked.
        with closing(sqlite3.connect(self.ag_db)) as locker:
            locker.isolation_level = None
            locker.execute("BEGIN EXCLUSIVE")
            try:
                report = sohbetler.tara(
                    self.vault, gun=10, now=NOW,
                    claude_dir=self.root / "yok1", codex_dir=self.root / "yok2", antigravity_db=self.ag_db,
                )
            finally:
                locker.execute("ROLLBACK")
        self.assertEqual(report["ozet"]["antigravity"]["durum"], "ok")
        self.assertEqual(report["ozet"]["antigravity"]["kullanici"], 1)

        # Corrupt / unreadable DB where both mode=ro and temp copy fail -> "okunamadı"
        bad_db = self.root / "corrupt.db"
        bad_db.write_bytes(b"not a sqlite database at all")
        report_bad = sohbetler.tara(
            self.vault, gun=10, now=NOW,
            claude_dir=self.root / "yok1", codex_dir=self.root / "yok2", antigravity_db=bad_db,
        )
        self.assertEqual(report_bad["ozet"]["antigravity"]["durum"], "okunamadı")
        self.assertEqual(len(report_bad["okunamayan"]), 1)
        self.assertIn("okunamadı", sohbetler.markdown_ozet(report_bad))

        # When both direct connection and temp-copy connection fail, client reports "okunamadı"
        with patch.object(sohbetler.sqlite3, "connect", side_effect=sqlite3.OperationalError("database is locked")):
            report_locked = sohbetler.tara(
                self.vault, gun=10, now=NOW,
                claude_dir=self.root / "yok1", codex_dir=self.root / "yok2", antigravity_db=self.ag_db,
            )
        self.assertEqual(report_locked["ozet"]["antigravity"]["durum"], "okunamadı")

    def test_cli_installed_beyin_py_is_read_only_and_supports_markdown_and_json(self):
        build_claude_fixtures(self.claude_dir)
        build_codex_fixtures(self.codex_dir)
        build_antigravity_fixtures(self.ag_db)
        now_real = datetime.now(timezone.utc)
        recent_iso = (now_real - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        write_jsonl(
            self.claude_dir / "-home-u-now" / "cccccccc-0000-0000-0000-000000000001.jsonl",
            [{"type": "user", "sessionId": "cccccccc-0000-0000-0000-000000000001", "cwd": "/home/u/now",
              "timestamp": recent_iso, "message": {"role": "user", "content": "Bugünkü test sohbeti"}},
             {"type": "assistant", "sessionId": "cccccccc-0000-0000-0000-000000000001",
              "timestamp": recent_iso, "message": {"role": "assistant", "content": "Test cevabı"}}],
        )

        # 1. Source CLI with uninitialized state must NOT create state directory or files
        fresh_state = self.root / "uncreated_state"
        env = dict(
            isolated_env(self.root / "home"),
            BEYIN_SOHBETLER_CLAUDE_DIR=str(self.claude_dir),
            BEYIN_SOHBETLER_CODEX_DIR=str(self.codex_dir),
            BEYIN_SOHBETLER_ANTIGRAVITY_DB=str(self.ag_db),
        )
        res = subprocess.run(
            [sys.executable, str(ROOT / "scripts/beyin_v3.py"), "--vault", str(self.vault),
             "--state", str(fresh_state), "sohbetler", "--gun", "3"],
            capture_output=True, text=True, encoding="utf-8", env=env, timeout=30,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("# Sohbet taraması (son 3 gün)", res.stdout)
        self.assertIn("cccccccc", res.stdout)
        self.assertFalse(fresh_state.exists())

        # 2. Installed vault beyin.py (Markdown default + --json) writes nothing to vault or state
        inst_vault = self.root / "inst_vault"
        inst_state = self.root / "inst_state"
        inst_vault.mkdir()
        self.assertEqual(install(inst_vault, inst_state, env).returncode, 0)
        before_vault = snapshot(inst_vault)
        before_state = snapshot(inst_state)

        md_run = run_python(inst_vault / "beyin.py", ["sohbetler", "--gun", "3"], inst_vault, env)
        self.assertEqual(md_run.returncode, 0, md_run.stderr.decode("utf-8", errors="replace"))
        md_text = md_run.stdout.decode("utf-8")
        self.assertIn("# Sohbet taraması (son 3 gün)", md_text)
        self.assertIn("Bugünkü test sohbeti", md_text)

        json_run = run_python(inst_vault / "beyin.py", ["sohbetler", "--gun", "3", "--json"], inst_vault, env)
        self.assertEqual(json_run.returncode, 0, json_run.stderr.decode("utf-8", errors="replace"))
        payload = json.loads(json_run.stdout.decode("utf-8"))
        self.assertEqual(payload["gun"], 3)
        self.assertTrue(any(r["id8"] == "cccccccc" for r in payload["kayitsiz_kullanici_oturumlari"]))

        self.assertEqual(snapshot(inst_vault), before_vault)
        self.assertEqual(snapshot(inst_state), before_state)


if __name__ == "__main__":
    unittest.main()
