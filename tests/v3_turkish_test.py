#!/usr/bin/env python3
"""Turkish suffix folding in retrieval: synthetic local vaults only, no network."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('v3_turkish_evaluator', ROOT / 'scripts/evaluate_v3.py')
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)

# (root as a note writes it, inflected form as a user types it). Both directions must retrieve.
PAIRS = (
    ('fark', 'farkı'), ('not', 'notlar'), ('rapor', 'raporlardan'), ('proje', 'projede'),
    ('kütüphane', 'kütüphanesi'), ('toplantı', 'toplantıda'), ('dükkan', 'dükkanında'),
    ('çoban', 'çobanın'), ('yayın', 'yayında'), ('kartal', 'kartalların'),
    ('berber', 'berberlerin'), ('köşe', 'köşelerde'), ('şişe', 'şişeden'),
    ('çatal', 'çatallarda'), ('kitap', 'kitaplar'), ('karar', 'kararı'),
    ('durum', 'durumu'), ('sunucu', 'sunucularda'), ('araba', 'arabanın'),
    ('neden', 'nedenleri'), ('kapı', 'kapısında'), ('orman', 'ormanda'),
    # Consonant alternation: the final k/t/p softens before a vowel suffix.
    ('grafik', 'grafiği'), ('kilit', 'kilidi'), ('uyuşmazlık', 'uyuşmazlığı'),
    ('dolap', 'dolabı'), ('renk', 'rengi'), ('köpek', 'köpeğin'),
)

# Pairs that must stay apart: a stemmer that merges these turns recall into noise.
NEGATIVES = (
    ('not', 'nota'), ('kar', 'karar'), ('kara', 'karar'), ('sinem', 'sinema'),
    ('bir', 'birim'), ('kod', 'kodla'), ('gol', 'golden'), ('tab', 'table'),
    ('hand', 'handle'), ('gar', 'garden'), ('sta', 'state'), ('list', 'listen'),
    ('dur', 'durum'), ('sür', 'sürüm'), ('yay', 'yayın'), ('haf', 'hafta'),
)

FILLER = 'Bu sentetik test kaydıdır.'


class VaultTestCase(unittest.TestCase):
    def setUp(self):
        self.module = evaluator.load_runtime()
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-turkish-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.store = self.module.MemoryStore(self.root / 'runtime', self.vault)
        self.addCleanup(lambda: evaluator.close_store(self.store))

    def ingest(self, id, text, source, updated_at='2026-09-18T10:00:00Z'):
        path = self.vault / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        self.store.ingest({'id': id, 'kind': 'note', 'status': 'active', 'visibility': 'internal',
                           'text': text, 'facts': {}, 'source': source, 'updated_at': updated_at})

    def ids(self, query, **kwargs):
        return [record['id'] for record in self.store.retrieve(query, **kwargs)['records']]


class TurkishStemTest(unittest.TestCase):
    """Token level: one canonical stem per word, identical on both sides of the query."""

    def setUp(self):
        self.module = evaluator.load_runtime()

    def stem(self, word):
        tokens = self.module._tokens(word)
        self.assertEqual(len(tokens), 1, word)
        return tokens.pop()

    def test_inflected_forms_fold_onto_the_same_stem(self):
        for root, inflected in PAIRS:
            with self.subTest(root=root):
                self.assertEqual(self.stem(root), self.stem(inflected))

    def test_unrelated_words_stay_apart(self):
        for left, right in NEGATIVES:
            with self.subTest(pair=(left, right)):
                self.assertNotEqual(self.stem(left), self.stem(right))

    def test_stemming_replaces_rather_than_expands(self):
        # The strict gate counts matched query words, so a word may never become two tokens.
        self.assertEqual(len(self.module._tokens('kararlarında toplantıların notları')), 3)

    def test_turkish_content_words_are_no_longer_stopwords(self):
        for word in ('not', 'karar', 'proje', 'durum', 'neden'):
            with self.subTest(word=word):
                self.assertNotIn(self.stem(word), self.module.STOPWORDS)


class TurkishRetrievalMatrixTest(VaultTestCase):
    def matrix(self, written, asked):
        for index, pair in enumerate(PAIRS):
            self.ingest('rec-%02d' % index, pair[written] + ' hakkında kısa kayıt. ' + FILLER,
                        'notes/rec-%02d.md' % index)
        for index, pair in enumerate(PAIRS):
            with self.subTest(query=pair[asked]):
                self.assertEqual(self.ids(pair[asked]), ['rec-%02d' % index])

    def test_inflected_query_finds_the_root_bearing_note(self):
        self.matrix(written=0, asked=1)

    def test_root_query_finds_the_inflected_note(self):
        self.matrix(written=1, asked=0)


class TurkishIssueCaseTest(VaultTestCase):
    """The two cases reported in issue #48, including the newer irrelevant report."""

    def setUp(self):
        super().setUp()
        self.ingest('kisa-not', 'Ahmet ile Mehmet arasında 5 yaş fark var.',
                    'notes/kisa_not.md', updated_at='2026-09-10')
        self.ingest('uzun-rapor', 'Şirket faaliyet raporu. Personel yaş ortalaması ve '
                    'departman dağılımı ayrıntılı olarak incelendi. ' + FILLER * 20,
                    'notes/uzun_rapor.md', updated_at='2026-09-18')
        self.ingest('toplanti-notu', 'Toplantı için kısa bir not aldım.', 'notes/toplanti.md')

    def test_inflected_query_outranks_the_newer_irrelevant_report(self):
        self.assertEqual(self.ids('yaş farkı')[0], 'kisa-not')

    def test_literal_query_still_works(self):
        self.assertEqual(self.ids('arasında kaç yaş fark var')[0], 'kisa-not')

    def test_notlar_returns_the_note_that_says_not(self):
        self.assertEqual(self.ids('notlar'), ['toplanti-notu'])


class TurkishStrictContextTest(VaultTestCase):
    """Strict per-turn context still needs two matched query words, inflected or not."""

    def setUp(self):
        super().setUp()
        self.ingest('yedekleme', 'Kütüphane sunucusunda gece yedeklemesi çalışıyor.',
                    'knowledge/yedekleme.md')
        self.ingest('mutfak', 'Mutfak alışverişi: elma, ekmek, zeytinyağı.', 'notes/mutfak.md')
        self.ingest('gunluk', 'Gün sonu kaydı. ' + FILLER * 30, 'daily/2026-09-18.md')

    def test_one_inflected_word_cannot_clear_the_strict_gate(self):
        self.assertEqual(self.ids('kütüphanesi', strict=False), ['yedekleme'])
        self.assertEqual(self.ids('kütüphanesi', strict=True), [])

    def test_two_inflected_words_still_reach_strict_context(self):
        self.assertEqual(self.ids('kütüphanenin yedeklemeleri', strict=True), ['yedekleme'])


# (form a note writes, form a user types): verb conjugations and EN<->TR technical terms.
VERB_PAIRS = (
    ('kurtarma prosedürü', 'kurtardık'), ('saklama', 'saklıyoruz'), ('deneme', 'denedik'),
    ('depolama', 'depoluyoruz'), ('taşması', 'taştı'), ('okuma', 'okuyacak'),
    ('kullanmak', 'kullanacağız'), ('yapılandırma', 'yapılandırdık'),
)
GLOSSARY_PAIRS = (
    ('veritabanı', 'database'), ('önbellek', 'cache'), ('kilit', 'lock'), ('oturumu', 'sessions'),
    ('güvenlik', 'security'), ('bağımlılık', 'dependencies'), ('göç', 'migration'), ('kuyruk', 'queue'),
)


class VerbAndGlossaryTest(VaultTestCase):
    def matrix(self, pairs, written, asked):
        for index, pair in enumerate(pairs):
            self.ingest('rec-%02d' % index, pair[written] + ' hakkında kısa kayıt. ' + FILLER, 'notes/rec-%02d.md' % index)
        for index, pair in enumerate(pairs):
            with self.subTest(query=pair[asked]):
                self.assertEqual(self.ids(pair[asked]), ['rec-%02d' % index])

    def test_conjugated_query_finds_the_verbal_noun_and_back(self):
        self.matrix(VERB_PAIRS, written=0, asked=1)

    def test_verbal_noun_query_finds_the_conjugated_note(self):
        self.matrix(VERB_PAIRS, written=1, asked=0)

    def test_english_query_finds_the_turkish_note(self):
        self.matrix(GLOSSARY_PAIRS, written=0, asked=1)

    def test_turkish_query_finds_the_english_note(self):
        self.matrix(GLOSSARY_PAIRS, written=1, asked=0)

    def test_the_reported_question_finds_the_decision(self):
        self.ingest('karar', '# Veritabanı kararı\n\nProje için PostgreSQL seçildi çünkü JSONB desteği var.',
                    'knowledge/karar.md')
        self.ingest('mutfak', 'Mutfak alışverişi: elma, ekmek.', 'notes/mutfak.md')
        self.assertEqual(self.ids('hangi database kullanıyoruz'), ['karar'])

    def test_no_glossary_term_turns_a_turkish_word_into_a_stopword(self):
        for verbs, synonyms in self.module._SYNONYMS.items():
            with self.subTest(verbs=verbs):
                self.assertEqual({v for v in synonyms.values() if v in self.module.STOPWORDS}, set())

    def test_istik_nouns_are_not_read_as_past_tense(self):
        tokens = self.module._search_tokens
        self.assertEqual(tokens('istatistik'), tokens('istatistiği'))

    def test_strict_context_does_not_fold_verbs(self):
        # Generic command verbs would otherwise pull every note that conjugates them.
        self.assertNotEqual(self.module._tokens('gösteriyor'), self.module._tokens('göster'))
        self.assertEqual(self.module._search_tokens('gösteriyor'), self.module._search_tokens('göster'))
        self.ingest('rapor', 'Panel haftalık sonuçları gösteriyor ve tabloyu yeniliyor.', 'notes/rapor.md')
        self.assertEqual(self.ids('sonuçları göster', strict=True), [])


class PrefixSearchTest(VaultTestCase):
    """Explicit search matches abbreviations by prefix; strict per-turn context stays exact."""

    def setUp(self):
        super().setUp()
        self.ingest('pg', 'PostgreSQL bağlantıları HikariCP ile yönetiliyor.', 'knowledge/pg.md')
        self.ingest('ui', 'Arayüzde handle edilen olaylar.', 'notes/ui.md')

    def test_abbreviation_finds_the_full_name(self):
        self.assertEqual(self.ids('postgres'), ['pg'])
        self.assertEqual(self.ids('hikari postgres'), ['pg'])

    def test_strict_context_does_not_use_prefixes(self):
        self.assertEqual(self.ids('postgres hikari', strict=True), [])

    def test_terms_under_the_minimum_do_not_prefix_match(self):
        self.assertEqual(self.ids('hand'), [])

    def test_exact_match_outranks_a_newer_prefix_match(self):
        self.ingest('exact', 'Havuz boyutu 20 bağlantı.', 'notes/exact.md', updated_at='2026-09-01')
        self.ingest('prefix', 'Havuz boyutlandırması yapıldı.', 'notes/prefix.md', updated_at='2026-09-30')
        self.assertEqual(self.ids('havuz boyutu')[:2], ['exact', 'prefix'])


class LegacyStateTest(VaultTestCase):
    """Tokens are computed per query, so a vault indexed before the stemmer needs no reindex."""

    LEGACY = {'facts': {}, 'id': 'eski-kayit', 'kind': 'note', 'revision': 1,
              'source': 'notes/eski.md', 'status': 'active', 'supersedes': [],
              'text': 'Dükkanın yayın kararı defterde duruyor.',
              'updated_at': '2026-09-01', 'visibility': 'internal'}

    def test_no_token_index_is_persisted(self):
        self.ingest('taze', 'Kütüphane kaydı.', 'notes/taze.md')
        with sqlite3.connect(self.store.database) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            payload = db.execute("SELECT payload FROM records WHERE id='taze'").fetchone()[0]
        db.close()
        self.assertEqual(tables - {'sqlite_sequence'}, {'records', 'receipts', 'metadata', 'events'})
        self.assertEqual(set(json.loads(payload)) & {'tokens', 'vocabulary', 'terms'}, set())

    def test_state_written_before_the_stemmer_answers_inflected_queries(self):
        source = self.vault / self.LEGACY['source']
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(self.LEGACY['text'], encoding='utf-8')
        record = dict(self.LEGACY, source_sha256=self.module.hashlib.sha256(
            source.read_bytes()).hexdigest())
        # Byte-for-byte the row the pre-stemmer release wrote: same schema, same payload.
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        with sqlite3.connect(self.store.database) as db:
            db.execute('INSERT INTO records VALUES (?,?)', (record['id'], payload))
        db.close()
        reopened = self.module.MemoryStore(self.root / 'runtime', self.vault)
        self.addCleanup(lambda: evaluator.close_store(reopened))
        found = reopened.retrieve('dükkanlardaki yayınlar')
        self.assertEqual([item['id'] for item in found['records']], ['eski-kayit'])


if __name__ == '__main__':
    unittest.main()
