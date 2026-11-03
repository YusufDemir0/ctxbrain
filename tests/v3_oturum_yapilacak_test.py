"""Session cards rebuild Last-Session.md; Yapılacaklar.md records and closes work."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from v3_package_helpers import ROOT, install, isolated_env, run_python

sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
import beyin_v3_oturum as oturum  # noqa: E402
import beyin_v3_yapilacaklar as todo  # noqa: E402


class OturumTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-oturum-test-')
        self.vault = Path(self.tmp.name) / 'vault'
        (self.vault / '🔮 850-Companion').mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def last(self):
        return (self.vault / '🔮 850-Companion/Last-Session.md').read_text(encoding='utf-8')

    def test_parallel_sessions_keep_their_own_cards(self):
        oturum.yaz(self.vault, None, 'aaaaaaaa11', 'api', '- birinci', proje='web')
        oturum.yaz(self.vault, None, 'bbbbbbbb22', 'tez', '- ikinci', proje='okul')
        text = self.last()
        self.assertIn('· api · aaaaaaaa', text)
        self.assertIn('· tez · bbbbbbbb', text)
        self.assertEqual(len(oturum.liste(self.vault)), 2)

    def test_same_session_and_label_updates_in_place(self):
        first = oturum.yaz(self.vault, None, 'aaaaaaaa', 'api', '- eski')
        second = oturum.yaz(self.vault, None, 'aaaaaaaa', 'api', '- yeni')
        self.assertFalse(first['updated'])
        self.assertTrue(second['updated'])
        self.assertEqual(first['card'], second['card'])
        self.assertIn('- yeni', self.last())
        self.assertNotIn('- eski', self.last())

    def test_summary_stays_under_budget_and_links_the_rest(self):
        for n in range(12):
            oturum.yaz(self.vault, None, f'{n:08x}', f'is {n}', '- ' + 'x' * 600, proje=f'p{n}')
        text = self.last()
        self.assertLessEqual(len(text), 3000)
        self.assertIn('## Diğer kartlar', text)

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            oturum.yaz(self.vault, None, 'zz', 'api', '- x')
        with self.assertRaises(ValueError):
            oturum.yaz(self.vault, None, 'aaaaaaaa', 'a · b', '- x')
        with self.assertRaises(ValueError):
            oturum.yaz(self.vault, None, 'aaaaaaaa', 'api', '   ')


class YapilacakTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-yapilacak-test-')
        self.vault = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_list_done_round_trip(self):
        self.assertEqual(todo.bekleyenler(self.vault), [])
        first = todo.ekle(self.vault, 'giriş sayfasını düzelt', proje='web', not_='mobilde taşıyor')
        second = todo.ekle(self.vault, 'kaynakçayı güncelle', proje='tez')
        self.assertNotEqual(first, second)
        self.assertEqual([i for i, _ in todo.bekleyenler(self.vault)], [first, second])
        todo.uygulandi(self.vault, first, 'css düzeltildi')
        self.assertEqual([i for i, _ in todo.bekleyenler(self.vault)], [second])
        text = (self.vault / 'Yapılacaklar.md').read_text(encoding='utf-8')
        done = text.split(todo.DONE, 1)[1]
        self.assertIn(f'**{first}**', done)
        self.assertIn('Sonuç: css düzeltildi', done)
        self.assertIn('Not: mobilde taşıyor', done)
        with self.assertRaises(ValueError):
            todo.uygulandi(self.vault, first, 'tekrar')

    def test_hook_notice_reads_intent(self):
        self.assertEqual(todo.hook_notice(self.vault, 'SessionStart'), '')
        todo.ekle(self.vault, 'bir iş', proje='web')
        self.assertIn('1 bekleyen iş (web)', todo.hook_notice(self.vault, 'SessionStart'))
        self.assertIn('UYGULAMA', todo.hook_notice(self.vault, 'UserPromptSubmit', 'bunu yapılacaklara ekle'))
        self.assertIn('uygulama)', todo.hook_notice(self.vault, 'UserPromptSubmit', 'YAPILACAKLARI UYGULA'))
        self.assertEqual(todo.hook_notice(self.vault, 'UserPromptSubmit', 'merhaba'), '')


class CliTest(unittest.TestCase):
    def test_installed_cli_runs_both_commands(self):
        with tempfile.TemporaryDirectory(prefix='v3-oturum-cli-') as t:
            root = Path(t); vault = root / 'vault'; vault.mkdir(); state = root / 'state'
            env = isolated_env(root / 'home')
            installed = install(vault, state, env)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            (vault / '🔮 850-Companion').mkdir(exist_ok=True)
            body = root / 'kart.md'; body.write_text('- kurulum denendi\n', encoding='utf-8')
            wrote = run_python(vault / 'beyin.py', ['oturum', 'yaz', '--session', 'cafebabe99', '--etiket', 'deneme',
                                                    '--proje', 'ctx', '--dosya', body], vault, env)
            self.assertEqual(wrote.returncode, 0, wrote.stderr)
            self.assertIn('kurulum denendi', (vault / '🔮 850-Companion/Last-Session.md').read_text(encoding='utf-8'))
            added = run_python(vault / 'beyin.py', ['yapilacak', 'ekle', '--proje', 'ctx', 'testi yaz'], vault, env)
            self.assertEqual(added.returncode, 0, added.stderr)
            item = added.stdout.decode().strip()
            listed = run_python(vault / 'beyin.py', ['yapilacak', 'liste'], vault, env)
            self.assertIn(item, listed.stdout.decode())
            done = run_python(vault / 'beyin.py', ['yapilacak', 'uygulandi', item, '--sonuc', 'yazıldı'], vault, env)
            self.assertEqual(done.returncode, 0, done.stderr)
            agents = (vault / 'AGENTS.md').read_text(encoding='utf-8')
            self.assertIn('beyin.py oturum yaz', agents)
            self.assertIn('beyin.py yapilacak ekle', agents)
            json.loads((vault / '.beyin-runtime.json').read_text())


if __name__ == '__main__':
    unittest.main()
