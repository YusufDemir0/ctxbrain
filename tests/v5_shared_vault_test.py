"""Concurrent writers, opt-in branch checks and origin on a synthetic installed vault."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from v3_package_helpers import inherited_env

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
from beyin_v3_companion import DEFAULT_DIRECTORY
from beyin_v3_sync import parse
from beyin_v3_vault import file_lock


class SharedVaultTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v5-shared-', dir=ROOT)
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name) / 'vault'
        self.state = Path(tmp.name) / 'state'
        self.vault.mkdir()
        self.env = inherited_env(BEYIN_V3_NO_SPAWN='1', BEYIN_UPDATES_OFF='1',
                                 PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        installed = self.run_python(ROOT / 'scripts/install_v3.py', '--vault', str(self.vault), '--state', str(self.state))
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.entry = self.vault / 'beyin.py'
        self.companion = self.vault / DEFAULT_DIRECTORY
        self.summary = self.companion / 'Last-Session.md'

    def run_python(self, script, *words, body=None):
        return subprocess.run([sys.executable, str(script), *words], input=body,
                              capture_output=True, encoding='utf-8', timeout=25, env=self.env)

    def cli(self, *words, body=None):
        result = self.run_python(self.entry, *words, body=body)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def hook(self, harness, event, **payload):
        script = self.vault / '.claude/scripts/beyin_v3_hook.py'
        result = self.run_python(script, '--vault', str(self.vault), '--state', str(self.state),
                                 '--harness', harness, '--event', event, body=json.dumps(payload))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def test_two_concurrent_writers_keep_both_cards_and_their_summary(self):
        files = [self.vault / f'body-{i}.txt' for i in range(2)]
        commands = []
        for i, body in enumerate(files):
            body.write_text(f'SYNTHETIC_CARD_{i}\n', encoding='utf-8')
            commands.append([sys.executable, str(self.entry), 'oturum', 'yaz',
                             '--session', f'abcdef0{i}abcd0123', '--etiket', f'test-{i}', '--dosya', str(body)])
        with subprocess.Popen(commands[0], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env) as first, \
                subprocess.Popen(commands[1], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env) as second:
            for writer in (first, second):
                _, error = writer.communicate(timeout=15)
                self.assertEqual(writer.returncode, 0, error.decode('utf-8'))
        summary = self.summary.read_text(encoding='utf-8')
        cards = list((self.companion / 'Oturumlar').glob('*.md'))
        self.assertEqual(len(cards), 2)
        for i in range(2):
            self.assertIn(f'SYNTHETIC_CARD_{i}', summary)
            self.assertEqual(sum(f'SYNTHETIC_CARD_{i}' in path.read_text(encoding='utf-8') for path in cards), 1)

    def test_busy_summary_times_out_before_creating_a_card(self):
        original = self.summary.read_bytes()
        with file_lock(self.vault, self.summary):
            result = self.run_python(self.entry, 'oturum', 'yaz', '--session', 'cafebabe', '--etiket', 'test', body='BODY')
        self.assertNotEqual(result.returncode, 0)
        error = json.loads(result.stderr)
        self.assertEqual(error['error'], 'TimeoutError')
        self.assertIn('Last-Session.md', error['message'])
        self.assertEqual(self.summary.read_bytes(), original)
        self.assertEqual(list((self.companion / 'Oturumlar').glob('*.md')), [])

    @unittest.skipUnless(shutil.which('git'), 'git is needed for the synthetic worktree')
    def test_wrong_branch_refuses_writes_and_warns_in_sessionstart(self):
        subprocess.run(['git', 'init', '-q'], cwd=self.vault, env=self.env, check=True, timeout=10)
        subprocess.run(['git', 'symbolic-ref', 'HEAD', 'refs/heads/cloud'], cwd=self.vault,
                       env=self.env, check=True, timeout=10)
        self.cli('yapilacak', 'ekle', 'Cloud write before setting a preference')
        todo = self.vault / 'Yapılacaklar.md'
        original = todo.read_bytes()
        self.cli('preferences', '--beklenen-dal', 'main', '--context-mode', 'off')
        self.cli('preferences', '--profile', 'manual')
        for words in (('yapilacak', 'ekle', 'refused'), ('oturum', 'derle'),
                      ('companion-compact',), ('refleks', 'sozluk', '--olustur'),
                      ('refleks', 'gocet', '--uygula'), ('devir', 'kapat', 'abcdef01')):
            with self.subTest(words=words):
                result = self.run_python(self.entry, *words)
                self.assertNotEqual(result.returncode, 0)
                message = json.loads(result.stderr)['message']
                self.assertIn('cloud', message)
                self.assertIn('main', message)
        self.assertEqual(todo.read_bytes(), original)
        self.cli('companion-compact', '--dry-run')
        report = json.loads(self.cli('doctor'))
        self.assertEqual(report['status'], 'needs_attention')
        self.assertEqual(report['vault_branch']['status'], 'mismatch')
        self.assertIn(report['vault_branch']['warning'], self.cli('doctor', '--human'))
        opening = self.hook('claude', 'SessionStart', session_id='synthetic-branch')
        text = opening['hookSpecificOutput']['additionalContext']
        self.assertEqual(text.splitlines().count(report['vault_branch']['warning']), 1)
        subprocess.run(['git', 'symbolic-ref', 'HEAD', 'refs/heads/main'], cwd=self.vault,
                       env=self.env, check=True, timeout=10)
        self.cli('oturum', 'derle')
        self.assertEqual(json.loads(self.cli('doctor'))['vault_branch']['status'], 'match')
        subprocess.run(['git', 'symbolic-ref', 'HEAD', 'refs/heads/cloud'], cwd=self.vault,
                       env=self.env, check=True, timeout=10)
        self.cli('preferences', '--beklenen-dal', '')
        self.cli('yapilacak', 'ekle', 'Cloud write after clearing the preference')
        self.assertEqual(json.loads(self.cli('doctor'))['vault_branch']['status'], 'disabled')

    def test_configured_branch_allows_a_non_git_vault(self):
        # This fixture must live outside the checkout's parent Git repository.
        with tempfile.TemporaryDirectory(prefix='v5-non-git-') as directory:
            vault = Path(directory) / 'vault'
            vault.mkdir()
            cli = ROOT / 'scripts/beyin_v3.py'
            root = ('--vault', str(vault), '--state', str(vault.with_name('state')))
            for words in (('preferences', '--beklenen-dal', 'main'),
                          ('yapilacak', 'ekle', 'A todo outside Git'), ('doctor',)):
                result = self.run_python(cli, *root, *words)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['vault_branch']['status'], 'not_git')

    def test_origin_in_card_note_and_idempotent_receipt(self):
        session = '1234abcd5678efab1234abcd'
        options = ('--harness', 'pasla', '--model', 'model-synthetic', '--session', session)
        expected = {'harness': 'pasla', 'model': 'model-synthetic', 'session': session}
        self.cli('oturum', 'yaz', '--etiket', 'synthetic', *options, body='Synthetic card')
        card, = (self.companion / 'Oturumlar').glob('*.md')
        self.assertEqual(parse(card.read_text(encoding='utf-8'))[0], expected)
        source = 'knowledge/synthetic.md'
        self.cli('note-create', *options, body=json.dumps({'source': source, 'text': 'Synthetic knowledge'}))
        self.assertEqual(parse((self.vault / source).read_text(encoding='utf-8'))[0], expected)
        receipt_input = json.dumps({'event_id': 'synthetic', 'summary': 'Synthetic result', 'refs': [source]})
        receipt = json.loads(self.cli('receipt', *options, body=receipt_input))
        path = self.vault / receipt['source']
        original = path.read_bytes()
        self.cli('receipt', '--harness', 'codex', body=receipt_input)
        self.assertEqual(path.read_bytes(), original)
        metadata = parse(original.decode('utf-8'))[0]
        self.assertEqual({key: metadata[key] for key in expected}, expected)

    def test_write_hook_appends_origin_and_leaves_the_existing_bytes(self):
        folder = self.vault / 'knowledge'
        folder.mkdir()
        session = 'synthetic-session'
        receipt_id = hashlib.sha256(session.encode('utf-8')).hexdigest()[:24]
        original_header = b'---\r\ntitle: "A title"  # keep spacing\r\ntags: [one, two]\r\n'
        original_body = b'\r\n# Heading\r\nWith  spaces \r\nAnd no final newline'
        path = folder / 'manual.md'
        raw = original_header + b'---\r\n' + original_body
        path.write_bytes(raw)
        payload = {'tool_name': 'Write', 'tool_input': {'file_path': str(path)},
                   'session_id': session, 'model': 'model-synthetic'}
        with file_lock(self.vault, path):
            self.hook('claude', 'PostToolUse', **payload)
            self.assertEqual(path.read_bytes(), raw)
        self.hook('claude', 'PostToolUse', **payload)
        updated = path.read_bytes()
        self.assertTrue(updated.startswith(original_header))
        self.assertTrue(updated.endswith(b'---\r\n' + original_body))
        self.assertEqual(parse(updated.decode('utf-8'))[0],
                         {'title': 'A title', 'tags': ['one', 'two'], 'harness': 'claude',
                          'session': receipt_id, 'model': 'model-synthetic'})
        self.hook('codex', 'PostToolUse', **dict(payload, session_id='another'))
        self.assertEqual(path.read_bytes(), updated)

    def test_antigravity_write_hook_uses_the_documented_payload(self):
        hooks = json.loads((self.vault / '.agents/hooks.json').read_text(encoding='utf-8'))
        self.assertIn('PostToolUse', hooks['beyin-v3'])
        folder = self.vault / 'knowledge'
        folder.mkdir()
        path = folder / 'manual.md'
        raw = b'---\n{ "title" : "Keep spaces" }\n---\nBody with no newline'
        path.write_bytes(raw)
        self.assertEqual(self.hook('antigravity', 'PostToolUse', conversationId='synthetic-ag',
                                   workspacePaths=[str(self.vault)], modelName='model-synthetic',
                                   toolCall={'name': 'replace_file_content', 'args': {'TargetFile': str(path)}}), {})
        updated = path.read_bytes()
        self.assertTrue(updated.startswith(b'---\n{ "title" : "Keep spaces" '))
        self.assertTrue(updated.endswith(b'---\nBody with no newline'))
        self.assertEqual(parse(updated.decode('utf-8'))[0]['harness'], 'antigravity')

    def test_codex_patch_tags_an_unmarked_note(self):
        path = self.vault / 'knowledge/plain.md'
        path.parent.mkdir()
        original = '# Plain note\r\n\r\nA detail without a final newline'.encode()
        path.write_bytes(original)
        self.hook('codex', 'PostToolUse', tool_name='apply_patch', session_id='synthetic-codex',
                  cwd=str(self.vault), tool_input={'command': '*** Begin Patch\n*** Add File: knowledge/plain.md\n'
                                                               '+# Plain note\n*** End Patch'})
        metadata, body = parse(path.read_bytes().decode('utf-8'))
        self.assertEqual(metadata['harness'], 'codex')
        self.assertNotIn('model', metadata)
        self.assertEqual(body.encode(), original)


if __name__ == '__main__':
    unittest.main()
