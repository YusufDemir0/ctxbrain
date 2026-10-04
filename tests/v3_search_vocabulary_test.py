#!/usr/bin/env python3
"""Vocabulary-mismatch search benchmark: same corpus, different surface forms in the query."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "template/.claude/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("evaluate_v3_search", ROOT / "scripts/evaluate_v3_search.py")
evaluate_v3_search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluate_v3_search)

FIXTURE = ROOT / "tests/fixtures/v3/search_vocabulary.json"


class SearchVocabularyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = evaluate_v3_search.evaluate(FIXTURE, modes=["non_strict", "strict"])

    def test_fixture_identity(self):
        fixture, digest = evaluate_v3_search.read_fixture(FIXTURE)
        self.assertEqual(digest, "7c3405fa8b6508e76c4548aeef1d9e64b4e712d4b80dd06b1c0d18b9f280c26f")
        record_ids = {record["id"] for record in fixture["records"]}
        for case in fixture["cases"]:
            self.assertIn(case["target_id"], record_ids)

    def test_abbreviations_and_consonant_alternation_reach_the_top_five(self):
        # Before prefix matching and devoicing: 33% and 50% Recall@5.
        categories = self.report["modes"]["non_strict"]["categories"]
        for category in ("abbreviation_prefix", "consonant_alternation"):
            with self.subTest(category=category):
                self.assertEqual(categories[category]["recall_at_5"], 1.0)
        self.assertGreaterEqual(self.report["modes"]["non_strict"]["recall_at_5"], 0.90)

    def test_verbs_and_glossary_reach_the_top(self):
        # Before verb stems and the EN-TR glossary: "schema migration" was never found.
        categories = self.report["modes"]["non_strict"]["categories"]
        for category in ("verb_inflection", "synonym_crosslingual"):
            with self.subTest(category=category):
                self.assertEqual(categories[category]["recall_at_1"], 1.0)

    def test_field_weighted_ranking_puts_the_target_first(self):
        # 0.0 on match counts, where daily logs won every tie on recency; 0.923 field-weighted.
        self.assertGreaterEqual(self.report["modes"]["non_strict"]["recall_at_1"], 0.85)

    def test_strict_context_gains_only_from_devoicing(self):
        # Strict stays exact by design, so abbreviations remain a measured gap there.
        categories = self.report["modes"]["strict"]["categories"]
        self.assertGreaterEqual(categories["consonant_alternation"]["recall_at_1"], 0.5)
        self.assertEqual(categories["abbreviation_prefix"]["recall_at_5"], 0.0)


if __name__ == "__main__":
    unittest.main()
