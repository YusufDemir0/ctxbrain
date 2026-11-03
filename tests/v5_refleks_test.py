"""Reflexes: evidence weight, fading, core candidacy, scoped triggering and Kurallar.md migration."""
from datetime import date, timedelta
from pathlib import Path
import sys
import tempfile
import unittest

from v3_package_helpers import ROOT, install, isolated_env, run_python

sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
import beyin_v3_refleks as refleks  # noqa: E402

TODAY = date(2026, 11, 3)
COMPANION = '🔮 850-Companion'


def day(n):
    return (TODAY - timedelta(days=n)).isoformat()


def reflex(evidence, durum='aktif', kapsam=()):
    return {'id': 'r', 'durum': durum, 'kapsam': list(kapsam), 'tetik': [], 'metin': 'x',
            'kanit': [{'date': d, 'type': t, 'text': 'x'} for d, t in evidence]}


class WeightTest(unittest.TestCase):
    def test_evidence_halves_every_half_life(self):
        self.assertAlmostEqual(refleks.weight(reflex([(day(0), 'kural')]), TODAY), 1.0)
        self.assertAlmostEqual(refleks.weight(reflex([(day(60), 'kural')]), TODAY), 0.5)
        self.assertAlmostEqual(refleks.weight(reflex([(day(0), 'kural'), (day(0), 'ters')]), TODAY), 0.0)

    def test_firing_keeps_a_reflex_fresh(self):
        old = reflex([(day(200), 'kural')])
        self.assertEqual(refleks.state_of(old, TODAY), 'sonmus')
        self.assertEqual(refleks.state_of(old, TODAY, last_fired=day(10)), 'aktif')

    def test_core_never_fades(self):
        self.assertEqual(refleks.state_of(reflex([(day(400), 'kural')], durum='cekirdek'), TODAY), 'cekirdek')

    def test_core_needs_repetition_time_and_no_recent_contradiction(self):
        once = reflex([(day(0), 'kural')])
        self.assertFalse(refleks.core_candidate(once, TODAY))
        quick = reflex([(day(2), 'kural'), (day(1), 'duzeltme'), (day(0), 'karar')])
        self.assertFalse(refleks.core_candidate(quick, TODAY))  # three times in three days is not "over time"
        lasting = reflex([(day(50), 'kural'), (day(20), 'duzeltme'), (day(1), 'tekrar')])
        self.assertTrue(refleks.core_candidate(lasting, TODAY))
        doubted = reflex([(day(50), 'kural'), (day(20), 'duzeltme'), (day(1), 'tekrar'), (day(5), 'ters')])
        self.assertFalse(refleks.core_candidate(doubted, TODAY))


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v5-refleks-test-')
        root = Path(self.tmp.name)
        self.vault, self.state = root / 'vault', root / 'state'
        (self.vault / COMPANION / 'Refleksler').mkdir(parents=True)
        (self.vault / 'projeler' / 'magaza-erp').mkdir(parents=True)
        (self.vault / 'projeler' / 'video-kanali').mkdir(parents=True)
        (self.vault / COMPANION / 'Refleksler' / '_sozluk.md').write_text(
            '- magaza-erp: erp, mağaza, sevkiyat\n- video-kanali: video, kapak\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def fire(self, event, prompt='', paths=(), session='s1'):
        return refleks.trigger(self.vault, self.state, session, event, prompt, paths, today=TODAY)

    def test_dictionary_matches_suffixes_and_phrases_but_not_fragments(self):
        entries = refleks.dictionary(self.vault)
        self.assertEqual(refleks.scopes_in("ERP'de sevkiyatı düzelt", entries), {'magaza-erp'})
        self.assertEqual(refleks.scopes_in('Mağazanın stoğu', entries), {'magaza-erp'})
        self.assertEqual(refleks.scopes_in('yeni kapakları dene', entries), {'video-kanali'})
        self.assertEqual(refleks.scopes_in('superpower', entries), set())  # "erp" inside a word
        self.assertEqual(refleks.scopes_in('git geçmişi', entries), set())

    def test_scoped_reflex_fires_only_in_its_context_and_once_per_session(self):
        refleks.ekle(self.vault, 'Depocu kârı görmez', ['magaza-erp'], 'kural')
        refleks.ekle(self.vault, 'Önce gerekçeyi sor', [], 'kural')
        opening = self.fire('SessionStart')
        self.assertIn('Önce gerekçeyi sor', opening)
        self.assertNotIn('Depocu', opening)
        self.assertEqual(self.fire('UserPromptSubmit', 'git geçmişinde e-posta görünür mü'), '')
        turn = self.fire('UserPromptSubmit', 'sevkiyat ekranını düzeltelim')
        self.assertIn('Depocu kârı görmez', turn)
        self.assertIn('etkin kapsam: magaza-erp', turn)
        self.assertEqual(self.fire('UserPromptSubmit', 'sevkiyat devam'), '')  # already said this session
        self.assertIn('Depocu', self.fire('UserPromptSubmit', 'sevkiyat', session='s2'))

    def test_edited_file_activates_its_project(self):
        refleks.ekle(self.vault, 'Kapakta iki satır yazı', ['video-kanali'], 'kural')
        self.fire('SessionStart')
        out = self.fire('PostToolUse', paths=[str(self.vault / 'projeler' / 'video-kanali' / 'notlar.md')])
        self.assertIn('Kapakta iki satır', out)

    def test_scope_stays_active_for_a_few_turns_then_lapses(self):
        refleks.ekle(self.vault, 'Depocu kârı görmez', ['magaza-erp'], 'kural')
        self.fire('SessionStart')
        self.fire('UserPromptSubmit', 'erp')
        record = refleks._read_json(refleks._session_path(self.state, 's1'), {})
        self.assertEqual(record['projects'], {'magaza-erp': refleks.SESSION_TURNS})
        for _ in range(refleks.SESSION_TURNS):
            self.fire('UserPromptSubmit', 'devam')
        self.assertEqual(refleks._read_json(refleks._session_path(self.state, 's1'), {})['projects'], {})

    def test_faded_project_reflex_returns_with_its_project_marked_old(self):
        refleks.ekle(self.vault, 'Canlı veriye dokunma', ['magaza-erp'], 'kural', tarih=day(300))
        refleks.ekle(self.vault, 'Eski genel alışkanlık', [], 'kural', tarih=day(300))
        opening = self.fire('SessionStart')
        self.assertNotIn('Eski genel', opening)  # a faded general reflex is forgotten
        turn = self.fire('UserPromptSubmit', 'erp canlı')
        self.assertIn('Canlı veriye dokunma', turn)
        self.assertIn('eski, doğrula', turn)

    def test_similar_reflex_is_offered_instead_of_duplicated(self):
        first = refleks.ekle(self.vault, 'Depo personeli kâr ve maliyet görmez', ['magaza-erp'], 'kural')
        again = refleks.ekle(self.vault, 'Depo personeli maliyet ve kâr göremez', ['magaza-erp'], 'duzeltme')
        self.assertEqual(again['status'], 'benzer_var')
        self.assertEqual(again['similar'][0]['id'], first['id'])
        added = refleks.ekle(self.vault, 'Depo personeli maliyet ve kâr göremez', ['magaza-erp'], 'duzeltme',
                             refleks_id=first['id'])
        self.assertEqual(added['status'], 'kanit_eklendi')
        self.assertEqual(len(refleks.load(self.vault)[0]['kanit']), 2)

    def test_unknown_scope_is_refused(self):
        with self.assertRaises(ValueError):
            refleks.ekle(self.vault, 'x', ['yok-boyle-proje'], 'kural')

    def test_core_candidate_is_announced_at_session_start(self):
        rid = refleks.ekle(self.vault, 'Önce gerekçeyi sor', [], 'kural', tarih=day(50))['id']
        refleks.ekle(self.vault, 'Önce gerekçeyi sor', [], 'tekrar', refleks_id=rid, tarih=day(20))
        refleks.ekle(self.vault, 'Önce gerekçeyi sor', [], 'duzeltme', refleks_id=rid, tarih=day(1))
        self.assertIn('çekirdeğe aday', self.fire('SessionStart'))
        refleks.set_core(self.vault, rid)
        self.assertNotIn('çekirdeğe aday', self.fire('SessionStart', session='s3'))

    def test_migration_moves_only_single_project_rules_and_keeps_a_backup(self):
        rules = self.vault / COMPANION / 'Kurallar.md'
        original = ('# Kullanıcının düzeltmeleri\n\n'
                    '- **2026-10-04 · fikir tartışması (Ada):** Önce gerekçeyi sor; örneğin ERP kararlarında da.\n'
                    '- **2026-10-05 · ERP depo:** Depocu kârı görmez.\n'
                    '  Sevk ekranında da.\n'
                    '- **2026-10-06 · video kapak:** Kapakta iki satır.\n'
                    '- **2026-10-07 · ERP videosu:** Tanıtım videosu kısa olsun.\n')
        rules.write_text(original, encoding='utf-8')
        plan = refleks.migrate(self.vault)
        self.assertFalse(plan['uygulandi'])
        self.assertEqual(rules.read_text(encoding='utf-8'), original)  # dry run writes nothing
        self.assertEqual(plan['kapsamlar'], {'magaza-erp': 1, 'video-kanali': 1})
        done = refleks.migrate(self.vault, apply=True, today=TODAY)
        left = rules.read_text(encoding='utf-8')
        self.assertIn('fikir tartışması', left)  # names ERP only as an example: stays global
        self.assertIn('Tanıtım videosu', left)  # names two projects: stays global
        self.assertNotIn('Depocu', left)
        self.assertNotIn('Sevk ekranında', left)
        archive = self.vault / COMPANION / done['arsiv'].split(COMPANION + '/', 1)[1]
        self.assertIn(original, archive.read_text(encoding='utf-8'))
        moved = {r['metin']: r for r in refleks.load(self.vault)}
        depo = moved['ERP depo: Depocu kârı görmez. Sevk ekranında da.']
        self.assertEqual(depo['kapsam'], ['magaza-erp'])
        self.assertEqual(depo['kanit'][0]['date'], '2026-10-05')


class TriggerGateTest(unittest.TestCase):
    def test_labelled_prompts_activate_exactly_their_scopes(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        import json
        import evaluate_v5_reflex as evaluate
        data = json.loads(evaluate.DEFAULT.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / COMPANION / 'Refleksler').mkdir(parents=True)
            (vault / COMPANION / 'Refleksler' / '_sozluk.md').write_text(
                '\n'.join(f"- {k}: {', '.join(v)}" for k, v in data['dictionary'].items()) + '\n', encoding='utf-8')
            result = evaluate.score(refleks.dictionary(vault), data['cases'])
        self.assertEqual(result['kacanlar'], [])


class CliTest(unittest.TestCase):
    def test_installed_cli_adds_lists_and_promotes(self):
        with tempfile.TemporaryDirectory(prefix='v5-refleks-cli-') as t:
            root = Path(t); vault = root / 'vault'; vault.mkdir(); state = root / 'state'
            env = isolated_env(root / 'home')
            self.assertEqual(install(vault, state, env).returncode, 0)
            (vault / 'projeler' / 'erp').mkdir(parents=True)
            added = run_python(vault / 'beyin.py', ['refleks', 'ekle', 'Depocu kârı görmez', '--kapsam', 'erp',
                                                   '--tur', 'kural'], vault, env)
            self.assertEqual(added.returncode, 0, added.stderr)
            rid = added.stdout.decode().split(':')[0]
            again = run_python(vault / 'beyin.py', ['refleks', 'ekle', 'Depocu kârı göremez', '--kapsam', 'erp'], vault, env)
            self.assertEqual(again.returncode, 3)
            self.assertIn(rid, again.stdout.decode())
            listed = run_python(vault / 'beyin.py', ['refleks', 'liste'], vault, env)
            self.assertIn('Depocu kârı görmez', listed.stdout.decode())
            up = run_python(vault / 'beyin.py', ['refleks', 'yukselt', rid], vault, env)
            self.assertIn('cekirdek', up.stdout.decode())
            words = run_python(vault / 'beyin.py', ['refleks', 'sozluk', '--olustur'], vault, env)
            self.assertIn('- erp:', words.stdout.decode())


if __name__ == '__main__':
    unittest.main()
