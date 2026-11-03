"""Opening context (5.0.3): said once per session, condensed before it is cut, topic-only search."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from v3_package_helpers import inherited_env

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
from beyin_v3_companion import gist, latest_card, outline, relevant, topic

COMPANION = '🔮 850-Companion'
DETAIL = 'uzun geçmiş anlatımı, eski kararlar ve ara notlar. ' * 12
THREADS = '# Threads\n\n## Active Threads\n\n' + ''.join(
    f'### Konu {n}\n- Sahip: kullanıcı.\n- Ayrıntı: {DETAIL}\n- Sonraki adım: KONU{n}_ADIM\n\n' for n in range(1, 10)
) + '## Closed Threads\nKAPALI_KONU\n'
CORE = ('# Düşünme ortağı\n\nBen Ada. IDENTITY_CANARY\n\n## Aktif alanlar\n'
        + ''.join(f'- **Alan {n}:** {DETAIL}\n' for n in range(1, 8))
        + '\n## Kalıcı tercihler\n- **Öncelik:** PREF_CANARY doğruluk önce gelir, sonra hız. ' + DETAIL + '\n')
HANDOFF = ('# Son oturum\n\n## 2026-11-04 02:01 · yeni · aaaa\n- NEWEST_CARD tamamı görünür.\n- İkinci satır NEWEST_DETAIL.\n\n'
           '## 2026-11-03 23:00 · eski · bbbb\n- OLDER_FIRST ilk satır.\n- OLDER_DETAIL ikinci satır.\n\n'
           '## Diğer kartlar\n- 2026-11-02 · a → `Oturumlar/a.md`\n- 2026-11-01 · b → `Oturumlar/b.md`\n')


class CondensedFormsTest(unittest.TestCase):
    def test_outline_names_every_thread_with_its_next_step(self):
        text = outline(THREADS.split('## Closed')[0])
        for n in range(1, 10):
            self.assertIn(f'### Konu {n}', text)
            self.assertIn(f'KONU{n}_ADIM', text)
        self.assertNotIn('Ayrıntı', text)
        self.assertIn('9 threads', text)

    def test_outline_without_a_next_step_keeps_the_last_line(self):
        text = outline('## Active Threads\n### A\n- ilk\n- SON_SATIR\n### B\n- Açık: ACIK_SATIR\n- sonra\n')
        self.assertIn('SON_SATIR', text)
        self.assertNotIn('- ilk', text)
        self.assertIn('ACIK_SATIR', text)
        self.assertNotIn('- sonra', text)

    def test_latest_card_keeps_the_newest_card_and_drops_the_list(self):
        text = latest_card(HANDOFF)
        for kept in ('NEWEST_CARD', 'NEWEST_DETAIL', '## 2026-11-03 23:00', 'OLDER_FIRST'):
            self.assertIn(kept, text)
        for dropped in ('OLDER_DETAIL', 'Oturumlar/a.md'):
            self.assertNotIn(dropped, text)
        self.assertIn('2 more listed', text)

    def test_gist_folds_current_work_and_keeps_every_preference(self):
        text = gist(CORE)
        self.assertIn('IDENTITY_CANARY', text)
        self.assertIn('- Alan 1 · Alan 2', text)
        self.assertIn('PREF_CANARY doğruluk önce gelir, sonra hız.', text)
        self.assertNotIn(DETAIL.strip(), text)
        self.assertLess(text.index('Alan 7'), text.index('## Kalıcı tercihler'))


class TopicTest(unittest.TestCase):
    def test_a_continuity_question_searches_only_its_topic(self):
        self.assertEqual(topic("zombi'de nerede kaldık"), 'zombi')
        self.assertEqual(topic('selam en son neler yapmıştık nerelerde kaldık ne alemdeyiz'), '')
        self.assertEqual(topic('What did we do last time?'), '')

    def test_nerelerde_kaldik_is_a_continuity_question_and_kargo_is_not(self):
        self.assertTrue(relevant('nerelerde kaldık'))
        self.assertFalse(relevant('kargo nerede kaldı'))


class OpeningOncePerSessionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v5-acilis-')
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name) / 'vault'
        self.state = Path(tmp.name) / 'state'
        self.directory = self.vault / COMPANION
        self.directory.mkdir(parents=True)
        for name, body in {'Core.md': CORE, 'Kurallar.md': '# Kurallar\n- RULE_CANARY: kısa yaz.\n',
                           'Last-Session.md': HANDOFF, 'Threads.md': THREADS,
                           'Journal.md': '# Journal\n## 2026-11-03\n- JOURNAL_CANARY\n'}.items():
            (self.directory / name).write_text(body, encoding='utf-8')
        (self.vault / '.beyin-preferences.json').write_text(json.dumps({'context_chars': 9000, 'context_mode': 'turn'}))
        self.env = inherited_env(BEYIN_V3_NO_SPAWN='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        self.sync()

    def sync(self):
        subprocess.run([sys.executable, str(ROOT / 'scripts/beyin_v3.py'), '--vault', str(self.vault),
                        '--state', str(self.state), 'sync'], capture_output=True, env=self.env, timeout=40, check=True)

    def hook(self, event, session, prompt=None):
        payload = {'hook_event_name': event, 'session_id': session, 'event_id': event + session + str(prompt)}
        if prompt:
            payload['prompt'] = prompt
        result = subprocess.run([sys.executable, str(ROOT / 'template/.claude/scripts/beyin_v3_hook.py'),
                                 '--vault', str(self.vault), '--state', str(self.state), '--harness', 'claude'],
                                input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8',
                                env=self.env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout).get('hookSpecificOutput', {}).get('additionalContext', '')

    def test_opening_fits_whole_in_condensed_form(self):
        text = self.hook('SessionStart', 'one')
        self.assertLessEqual(len(text), 9000)
        for canary in ['IDENTITY_CANARY', 'PREF_CANARY', 'RULE_CANARY', 'NEWEST_CARD', 'JOURNAL_CANARY'] + \
                [f'KONU{n}_ADIM' for n in range(1, 10)]:
            self.assertIn(canary, text)
        self.assertNotIn('KAPALI_KONU', text)

    def test_where_were_we_after_the_opening_is_not_repeated(self):
        self.assertIn('KONU9_ADIM', self.hook('SessionStart', 'one'))
        self.assertNotIn('IDENTITY_CANARY', self.hook('UserPromptSubmit', 'one', 'selam, neler yapmıştık?'))
        # Another session, or the same one after a companion source changed, gets it again.
        self.assertIn('IDENTITY_CANARY', self.hook('UserPromptSubmit', 'two', 'selam, neler yapmıştık?'))
        (self.directory / 'Last-Session.md').write_text(HANDOFF.replace('NEWEST_CARD', 'FRESH_CARD'), encoding='utf-8')
        self.sync()
        self.assertIn('FRESH_CARD', self.hook('UserPromptSubmit', 'one', 'nerede kalmıştık'))
