#!/usr/bin/env python3
"""Per-turn decision capture: extraction precision, the capture note, and the hook wiring."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'template/.claude/scripts'
HOOK = SCRIPTS / 'beyin_v3_hook.py'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import beyin_v3_capture as capture  # noqa: E402
import beyin_v3_preferences as preferences  # noqa: E402

DECISIONS = (
    'Veritabanı olarak PostgreSQL kullanalım.',
    'Frontend için React\'i seçtik çünkü ekip biliyor.',
    'Redis yerine Valkey kullan.',
    'Bence onay olmamalı, eş zamanlı olması daha iyi olur.',
    'We decided to ship on Friday.',
)
RULES = (
    'Bundan sonra commit mesajları İngilizce olsun.',
    'Testleri asla mocklama, gerçek veritabanına bağlan.',
    'Unutma, prod veritabanına doğrudan yazmıyoruz.',
    'From now on run the linter before committing.',
)
NOT_STATEMENTS = (
    'PostgreSQL mi kullanalım yoksa MySQL mi?',
    'Hangisini seçelim sence?',
    'Nasıl olmalı sence',
    'Bu hata neden oluyor?',
    'Şu dosyayı oku ve özetle.',
    'Testler geçti mi kontrol et.',
    '```\nalways_on = true\nnever_retry = false\n```',
    'SYNTHETIC_TRANSCRIPT_CANARY_NEVER_PERSIST',
)
NOW = datetime(2026, 10, 4, 14, 32, tzinfo=timezone.utc)


class StatementTest(unittest.TestCase):
    def test_decisions_and_rules_are_classified(self):
        for prompt in DECISIONS:
            with self.subTest(prompt=prompt):
                self.assertEqual(capture.statements(prompt), [('karar', prompt)])
        for prompt in RULES:
            with self.subTest(prompt=prompt):
                self.assertEqual(capture.statements(prompt), [('kural', prompt)])

    def test_questions_requests_and_code_are_not_statements(self):
        for prompt in NOT_STATEMENTS:
            with self.subTest(prompt=prompt):
                self.assertEqual(capture.statements(prompt), [])

    def test_only_the_stating_sentence_is_kept(self):
        prompt = 'Dosyayı incele. Veritabanı olarak PostgreSQL kullanalım. Sonra testleri çalıştır.'
        self.assertEqual(capture.statements(prompt), [('karar', 'Veritabanı olarak PostgreSQL kullanalım.')])

    def test_bounds(self):
        self.assertEqual(len(capture.statements(' '.join(DECISIONS + RULES))), capture.MAX_PER_PROMPT)
        self.assertEqual(capture.statements('Bundan sonra şunu yap. ' + 'x' * capture.MAX_PROMPT), [])
        kind, sentence = capture.statements('Bundan sonra ' + 'çok ' * 200 + 'dikkatli ol.')[0]
        self.assertEqual(len(sentence), capture.MAX_SENTENCE)
        self.assertTrue(sentence.endswith('…'))


class CaptureNoteTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-capture-test-')
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name) / 'vault'
        self.vault.mkdir()
        self.state = Path(tmp.name) / 'state'
        self.state.mkdir()
        self.note = self.vault / capture.DIRECTORY / '2026-10-04.md'

    def test_note_is_created_with_frontmatter_and_appended(self):
        self.assertEqual(capture.capture(self.vault, self.state, DECISIONS[0], 'session-abcdef12', NOW), 1)
        self.assertEqual(capture.capture(self.vault, self.state, RULES[0], 'session-abcdef12', NOW), 1)
        text = self.note.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('---\n{'))
        self.assertIn('# Yakalama 2026-10-04', text)
        self.assertIn('- 14:32 · karar · `session-` · ' + DECISIONS[0] + '\n', text)
        self.assertIn('- 14:32 · kural · `session-` · ' + RULES[0] + '\n', text)

    def test_a_repeated_statement_is_written_once(self):
        capture.capture(self.vault, self.state, DECISIONS[0], 's1', NOW)
        self.assertEqual(capture.capture(self.vault, self.state, DECISIONS[0], 's2', NOW), 0)
        self.assertEqual(capture.capture(self.vault, self.state, DECISIONS[0] + ' ' + DECISIONS[0], 's3', NOW), 0)
        self.assertEqual(self.note.read_text(encoding='utf-8').count(DECISIONS[0]), 1)

    def test_secrets_are_redacted_even_with_the_write_filter_off(self):
        self.assertFalse(preferences.read(self.vault)['secret_filter'])
        token = 'ghp_' + 'a' * 36
        capture.capture(self.vault, self.state, f'Bundan sonra deploy için {token} kullan.', 's', NOW)
        text = self.note.read_text(encoding='utf-8')
        self.assertNotIn(token, text)
        self.assertIn('[REDACTED]', text)

    def test_nothing_is_written_without_a_statement(self):
        self.assertEqual(capture.capture(self.vault, self.state, NOT_STATEMENTS[0], 's', NOW), 0)
        self.assertFalse((self.vault / 'knowledge').exists())

    @unittest.skipIf(os.name == 'nt', 'symlinks need privileges on Windows')
    def test_a_symlinked_capture_directory_is_refused(self):
        outside = self.vault.parent / 'outside'
        outside.mkdir()
        (self.vault / 'knowledge').mkdir()
        (self.vault / capture.DIRECTORY).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            capture.capture(self.vault, self.state, DECISIONS[0], 's', NOW)
        self.assertEqual(list(outside.iterdir()), [])

    def test_captured_statement_is_searchable(self):
        from beyin_v3_sync import SyncEngine
        capture.capture(self.vault, self.state, 'Önbellek için Valkey seçtik.', 's', NOW)
        engine = SyncEngine(self.vault, self.state)
        engine.sync()
        found = engine.store.retrieve('valkey önbellek')['records']
        self.assertEqual([record['source'] for record in found], [capture.DIRECTORY + '/2026-10-04.md'])


class CommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-capture-command-')
        self.addCleanup(tmp.cleanup)
        self.vault, self.state = Path(tmp.name) / 'vault', Path(tmp.name) / 'state'
        self.vault.mkdir()
        self.state.mkdir()

    def run_command(self, text):
        return capture.command(self.vault, self.state, text, 's', NOW)

    def seed(self):
        for prompt in ('Önbellek için Valkey seçtik.', 'Bundan sonra testleri İngilizce yaz.', 'Veritabanı olarak PostgreSQL kullanalım.'):
            capture.capture(self.vault, self.state, prompt, 's', NOW)

    def sentences(self):
        return [entry[5] for entry in capture.recent(self.vault)]

    def test_ordinary_prompts_are_not_commands(self):
        self.assertIsNone(self.run_command('Bundan sonra ctx: diye başlayan bir şey yaz.'))
        self.assertIsNone(self.run_command(None))

    def test_list_numbers_newest_first(self):
        self.assertIn('Henüz yakalanan', self.run_command('ctx: liste'))
        self.seed()
        reply = self.run_command('  CTX :  liste')
        self.assertIn(' 1. 2026-10-04 14:32 karar: Veritabanı olarak PostgreSQL kullanalım.', reply)
        self.assertIn(' 3. 2026-10-04 14:32 karar: Önbellek için Valkey seçtik.', reply)

    def test_forget_by_last_number_and_word(self):
        self.seed()
        self.assertEqual(self.run_command('ctx: unut son'), 'Silindi: Veritabanı olarak PostgreSQL kullanalım.')
        self.assertEqual(self.run_command('ctx: unut 2'), 'Silindi: Önbellek için Valkey seçtik.')
        self.assertEqual(self.run_command('ctx: unut ingilizce'), 'Silindi: Bundan sonra testleri İngilizce yaz.')
        self.assertEqual(self.sentences(), [])
        self.assertIn('# Yakalama 2026-10-04', (self.vault / capture.DIRECTORY / '2026-10-04.md').read_text(encoding='utf-8'))
        self.assertIn('Eşleşen kayıt yok', self.run_command('ctx: unut 9'))

    def test_an_ambiguous_word_deletes_nothing(self):
        self.seed()
        reply = self.run_command('ctx: unut e')
        self.assertIn('Birden çok kayıt eşleşti', reply)
        self.assertEqual(len(self.sentences()), 3)

    def test_save_writes_a_note_line_once_and_redacts(self):
        token = 'ghp_' + 'b' * 36
        self.assertEqual(self.run_command(f'ctx: kaydet Staging anahtarı {token} ile çalışıyor'), 'Kaydedildi.')
        self.assertEqual(self.run_command(f'ctx: kaydet Staging anahtarı {token} ile çalışıyor'), 'Bu cümle bugün zaten kayıtlı.')
        entry = capture.recent(self.vault)[0]
        self.assertEqual(entry[4], 'not')
        self.assertNotIn(token, entry[1])
        self.assertIn('Kaydedilecek cümleyi yaz', self.run_command('ctx: kaydet'))

    def test_switch_and_help(self):
        self.assertIn('kapatıldı', self.run_command('ctx: kapat'))
        self.assertFalse(capture.enabled(self.state))
        self.run_command('ctx: kaydet elle iki kelime')
        self.assertIn('KAPALI', self.run_command('ctx: liste'))
        self.assertIn('açıldı', self.run_command('ctx: aç'))
        self.assertTrue(capture.enabled(self.state))
        self.assertEqual(self.run_command('ctx: bilinmeyen'), capture.HELP)

    def test_terminal_command(self):
        cli = ROOT / 'scripts/beyin_v3.py'
        self.seed()
        result = subprocess.run([sys.executable, str(cli), '--vault', str(self.vault), '--state', str(self.state), 'ctx', 'unut', 'son'],
                                text=True, encoding='utf-8', capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'Silindi: Veritabanı olarak PostgreSQL kullanalım.')


class SettingTest(unittest.TestCase):
    def test_setting_is_machine_local_default_on_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            vault, state = Path(root) / 'vault', Path(root) / 'state'
            vault.mkdir()
            self.assertTrue(capture.enabled(state))
            capture.save(state, False)
            self.assertFalse(capture.enabled(state))
            preferences.save(vault, {}, profile='economical')
            self.assertFalse(capture.enabled(state), 'a profile switch leaves capture alone')
            # Older releases reject unknown .beyin-preferences.json keys, so rollback must not see one.
            self.assertNotIn('capture', json.loads((vault / '.beyin-preferences.json').read_text(encoding='utf-8')))
            capture.save(state, True)
            self.assertTrue(capture.enabled(state))
            (state / 'capture.json').write_text('{broken', encoding='utf-8')
            self.assertFalse(capture.enabled(state))


class HookCaptureTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-capture-hook-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.vault, self.state = root / 'vault', root / 'state'
        self.vault.mkdir()
        home = root / 'home'
        home.mkdir()
        self.env = {'HOME': str(home), 'USERPROFILE': str(home), 'PATH': os.defpath, 'TEMP': str(root),
                    'TMP': str(root), 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1',
                    'BEYIN_V3_NO_SPAWN': '1'}
        for key in ('SYSTEMROOT', 'WINDIR'):
            if key in os.environ:
                self.env[key] = os.environ[key]

    def prompt(self, text, extra=(), harness='claude', **fields):
        payload = dict({'hook_event_name': 'UserPromptSubmit', 'session_id': 'hook-session',
                        'event_id': 'e-' + str(abs(hash(text))), 'prompt': text}, **fields)
        result = subprocess.run([sys.executable, str(HOOK), '--vault', str(self.vault), '--state', str(self.state),
                                 '--harness', harness, *extra], input=json.dumps(payload), text=True,
                                encoding='utf-8', capture_output=True, env=self.env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_ctx_commands_are_answered_by_the_hook_and_never_reach_the_model(self):
        self.prompt('Bundan sonra testleri İngilizce yaz.')
        reply = self.prompt('ctx: liste')
        self.assertEqual(reply['decision'], 'block')
        self.assertIn('1. ', reply['reason'])
        self.assertEqual(self.prompt('ctx: unut son'), {'decision': 'block', 'reason': 'Silindi: Bundan sonra testleri İngilizce yaz.'})
        self.assertNotIn('ctx:', self.captured())
        other = self.prompt('ctx: liste', harness='opencode')
        self.assertIn('Henüz yakalanan', other['hookSpecificOutput']['additionalContext'])

    def test_the_new_sentence_is_written_after_this_turns_context(self):
        reply = self.prompt('Bundan sonra testleri İngilizce yaz.')
        self.assertNotIn('testleri İngilizce', json.dumps(reply, ensure_ascii=False))
        self.assertIn('testleri İngilizce', self.captured())

    def captured(self):
        directory = self.vault / capture.DIRECTORY
        return ''.join(path.read_text(encoding='utf-8') for path in sorted(directory.glob('*.md'))) if directory.is_dir() else ''

    def test_a_decision_is_written_during_the_turn(self):
        self.prompt('Dosyaları incele. Bundan sonra testleri İngilizce yaz.')
        self.assertIn('kural · `hook-ses` · Bundan sonra testleri İngilizce yaz.', self.captured())
        self.assertNotIn('Dosyaları incele', self.captured())

    def test_skipped_turns_write_nothing(self):
        self.prompt('SYNTHETIC_TRANSCRIPT_CANARY_NEVER_PERSIST')
        self.prompt('<task-notification>Bundan sonra testleri İngilizce yaz.</task-notification>')
        self.prompt('Bundan sonra testleri İngilizce yaz.', extra=['--metadata-only'])
        self.assertEqual(self.captured(), '')

    def test_capture_off_writes_nothing(self):
        capture.save(self.state, False)
        self.prompt('Bundan sonra testleri İngilizce yaz.')
        self.assertEqual(self.captured(), '')


if __name__ == '__main__':
    unittest.main()
