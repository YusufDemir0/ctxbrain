"""Devir kartı: limit/kesinti iş ortasında gelse de başka bir istemci vault'tan devam edebilir."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'template/.claude/scripts'
sys.path.insert(0, str(SCRIPTS))
import beyin_v3_devir as devir  # noqa: E402
import beyin_v3_oturum as oturum  # noqa: E402

SESSION = 'claude-oturum-1'
SID = hashlib.sha256(SESSION.encode()).hexdigest()[:8]


def claude_transcript(path):
    rows = [
        {"type": "user", "timestamp": "2026-11-14T10:00:00Z",
         "message": {"role": "user", "content": "<system-reminder>gizli bağlam</system-reminder>"}},
        {"type": "user", "timestamp": "2026-11-14T10:01:00Z",
         "message": {"role": "user", "content": "6 sahnelik videoyu zincirle üret"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "mcp__ccd_turn__update_plan",
             "input": {"items": [{"content": "Senaryo", "status": "in_progress"},
                                 {"content": "Klipler", "status": "pending"},
                                 {"content": "Kurgu", "status": "pending"}]}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": [{"type": "text", "text": "Plan shown"}]}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "mcp__ccd_turn__update_plan", "input": {"advance": True}},
            {"type": "tool_use", "name": "Write", "input": {"file_path": "/v/projeler/x/senaryo.md", "content": "..."}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "zincir.sh 6", "description": "Zinciri çalıştır"}},
            {"type": "text", "text": "S1-S5 hazır, S6 limit yüzünden bekliyor."}]}},
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def codex_rollout(path):
    rows = [
        {"type": "response_item", "timestamp": "2026-11-14T11:00:00Z", "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions for /v"}]}},
        {"type": "response_item", "timestamp": "2026-11-14T11:01:00Z", "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": "S6'yı 1.2 ile dene"}]}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
                                              "input": "tools.apply_patch(`*** Begin Patch\n*** Update File: tools/kurgu.py\n@@`)"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "update_plan",
                                              "arguments": json.dumps({"plan": [{"step": "S6 üret", "status": "completed"},
                                                                                {"step": "Kurgu", "status": "in_progress"}]})}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                              "content": [{"type": "output_text", "text": "Kurgu çalışıyor."}]}},
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


class DevirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v5-devir-test-')
        base = Path(self.tmp.name)
        self.vault, self.state = base / 'vault', base / 'state'
        (self.vault / '🔮 850-Companion').mkdir(parents=True)
        self.state.mkdir()
        self.transcript = base / 'claude.jsonl'
        claude_transcript(self.transcript)

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, **extra):
        return dict({"session_id": SESSION, "transcript_path": str(self.transcript)}, **extra)

    def last(self):
        return (self.vault / '🔮 850-Companion/Last-Session.md').read_text(encoding='utf-8')

    def test_limit_interruption_leaves_a_handoff_card_and_summary(self):
        card = devir.guncelle(self.vault, self.state, 'claude', self.payload(error='rate_limit'), 'StopFailure', project='video')
        self.assertIsNotNone(card)
        text = card.read_text(encoding='utf-8')
        self.assertIn('kesildi (rate_limit)', text)
        self.assertIn('6 sahnelik videoyu zincirle üret', text)
        self.assertNotIn('gizli bağlam', text)
        self.assertIn('### Görev listesi (1/3)', text)       # items + advance birleşti
        self.assertIn('- [>] Klipler', text)
        self.assertIn('`/v/projeler/x/senaryo.md`', text)
        self.assertIn('S6 limit yüzünden bekliyor', text)
        last = self.last()
        self.assertIn('## Yarım kalan işler (devir)', last)
        self.assertIn(f'beyin.py devir goster {SID}', last)

    def test_tool_events_are_throttled_but_turn_end_is_not(self):
        self.assertIsNotNone(devir.guncelle(self.vault, self.state, 'claude', self.payload(), 'PostToolUse'))
        self.assertIsNone(devir.guncelle(self.vault, self.state, 'claude', self.payload(), 'PostToolUse'))
        self.assertIsNotNone(devir.guncelle(self.vault, self.state, 'claude', self.payload(), 'Stop'))

    def test_own_session_card_closes_handoff_without_deleting(self):
        devir.guncelle(self.vault, self.state, 'claude', self.payload(), 'Stop')
        receipt_session = hashlib.sha256(SESSION.encode()).hexdigest()[:24]
        result = oturum.yaz(self.vault, None, receipt_session, 'video', '- bitti', proje='video')
        self.assertEqual(result['devir_closed'], 1)
        self.assertEqual(devir.acik(self.vault), [])
        archived = list((self.vault / '🔮 850-Companion/Devir/Arşiv').glob(SID + '-*.md'))
        self.assertEqual(len(archived), 1)
        self.assertIn('Durum: kapandı (oturum kartı yazıldı', archived[0].read_text(encoding='utf-8'))
        self.assertNotIn('Yarım kalan işler', self.last())

    def test_codex_rollout_is_parsed_and_detail_shows_turns(self):
        roll = Path(self.tmp.name) / 'rollout.jsonl'
        codex_rollout(roll)
        card = devir.guncelle(self.vault, self.state, 'codex', {"session_id": "codex-1", "transcript_path": str(roll)}, 'Stop')
        text = card.read_text(encoding='utf-8')
        self.assertIn("S6'yı 1.2 ile dene", text)
        self.assertNotIn('AGENTS.md instructions', text)
        self.assertIn('`tools/kurgu.py`', text)
        self.assertIn('- [x] S6 üret', text)
        self.assertIn('Kurgu çalışıyor.', text)
        detail = devir.goster(self.vault, hashlib.sha256(b'codex-1').hexdigest()[:8], detay=True)
        self.assertIn('## Sohbetin son turları', detail)
        self.assertIn("**Kullanıcı:** S6'yı 1.2 ile dene", detail)

    def test_finished_session_is_not_listed_as_unfinished(self):
        rows = [json.loads(l) for l in self.transcript.read_text(encoding='utf-8').splitlines()]
        rows.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "mcp__ccd_turn__wrap_up", "input": {"recap": "bitti"}}]}})
        self.transcript.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        card = devir.guncelle(self.vault, self.state, 'claude', self.payload(), 'Stop')
        self.assertIn('### Görev listesi (3/3)', card.read_text(encoding='utf-8'))
        self.assertEqual(len(devir.acik(self.vault)), 1)          # kart duruyor, `devir liste` görür
        self.assertNotIn('Yarım kalan işler', self.last())        # ama özet gürültü yapmıyor

    def test_no_transcript_or_no_content_writes_nothing(self):
        self.assertIsNone(devir.guncelle(self.vault, self.state, 'claude', {"session_id": SESSION}, 'Stop'))
        empty = Path(self.tmp.name) / 'empty.jsonl'
        empty.write_text('', encoding='utf-8')
        self.assertIsNone(devir.guncelle(self.vault, self.state, 'claude',
                                         {"session_id": SESSION, "transcript_path": str(empty)}, 'Stop'))
        self.assertFalse((self.vault / '🔮 850-Companion/Devir').exists())

    def test_hook_end_to_end_stopfailure_and_quiet_bash(self):
        hook = SCRIPTS / 'beyin_v3_hook.py'
        env = dict(os.environ, BEYIN_V3_SKIP_UPDATE_CHECK='1')

        def run(payload):
            return subprocess.run([sys.executable, str(hook), '--vault', str(self.vault), '--state', str(self.state),
                                   '--harness', 'claude'], input=json.dumps(payload), capture_output=True, text=True,
                                  timeout=60, env=env)

        out = run(self.payload(hook_event_name='StopFailure', error='rate_limit'))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), '{}')
        cards = list((self.vault / '🔮 850-Companion/Devir').glob(SID + '-claude.md'))
        self.assertEqual(len(cards), 1)
        self.assertIn('kesildi (rate_limit)', cards[0].read_text(encoding='utf-8'))
        out = run(self.payload(hook_event_name='PostToolUse', tool_name='Bash', tool_input={"command": "ls"}))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), '{}')
        # Bash bir düzenleme değil: receipt hatırlatması için oturum "düzenlendi" işaretlenmez
        self.assertFalse(list((self.state / 'receipt-reminders').glob('*.edited')))


if __name__ == '__main__':
    unittest.main()
