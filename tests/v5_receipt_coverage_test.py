"""Synthetic tests for two-tier receipt coverage, UUID session matching, and promptless exclusion."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from v3_package_helpers import inherited_env

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))

import beyin_v3_hook as hook
from beyin_entry import human_result
from beyin_v3_projections import _checkpoint_schema, _latest_receipts, receipt_coverage, record_checkpoints
from beyin_v3_sync import SyncEngine


class ReceiptCoverageV5Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.state = self.root / 'state'
        self.home = self.root / 'home'
        self.home.mkdir()
        self.env = inherited_env(
            HOME=str(self.home),
            USERPROFILE=str(self.home),
            BEYIN_V3_NO_SPAWN='1',
            PYTHONDONTWRITEBYTECODE='1',
            PYTHONIOENCODING='utf-8',
        )
        self.engine = SyncEngine(self.vault, self.state)
        self.source('notes/work.md', 'Synthetic work note.')

    def source(self, relative, body):
        self.engine.note_create(relative, body, {'id': relative.replace('/', '-'), 'project': 'demo'})

    def _doctor_json(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/beyin_v3.py'), '--vault', str(self.vault), '--state', str(self.state), 'doctor'],
            capture_output=True, text=True, encoding='utf-8', env=self.env, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_session_with_final_pure_qa_turn_stays_covered_in_both_metrics(self):
        t0 = time.time() - 120
        record_checkpoints(self.engine, [
            {'event': 'UserPromptSubmit', 'harness': 'claude', 'session': 'sess_qa_tail', 'at': t0},
            {'event': 'PostToolUse', 'harness': 'claude', 'session': 'sess_qa_tail', 'at': t0 + 10},
        ])
        self.engine.receipt('rc-edit', 'Implemented fix.', ['notes/work.md'], 'claude', session='sess_qa_tail')
        later = time.time() + 60
        record_checkpoints(self.engine, [
            {'event': 'UserPromptSubmit', 'harness': 'claude', 'session': 'sess_qa_tail', 'at': later},
            {'event': 'Stop', 'harness': 'claude', 'session': 'sess_qa_tail', 'at': later + 5},
        ])
        self.engine.sync()

        with self.engine.store._connect() as db:
            cov = receipt_coverage(db, now=later + 10)
        gaps = json.loads((self.state / 'receipt-gaps.json').read_text(encoding='utf-8'))

        self.assertEqual((cov['covered'], cov['total'], cov['ratio']), (1, 1, 1.0))
        self.assertEqual((cov['session']['covered'], cov['session']['total'], cov['session']['ratio']), (1, 1, 1.0))
        self.assertEqual((cov['last_edit']['covered'], cov['last_edit']['total'], cov['last_edit']['ratio']), (1, 1, 1.0))
        self.assertEqual(gaps['potential_missing_receipts'], 0)

    def test_edit_after_receipt_covered_for_session_but_missing_for_last_edit(self):
        t0 = time.time() - 120
        record_checkpoints(self.engine, [
            {'event': 'UserPromptSubmit', 'harness': 'codex', 'session': 'sess_edit_after', 'at': t0},
            {'event': 'PostToolUse', 'harness': 'codex', 'session': 'sess_edit_after', 'at': t0 + 5},
        ])
        self.engine.receipt('rc-early', 'Initial receipt.', ['notes/work.md'], 'codex', session='sess_edit_after')
        later = time.time() + 60
        record_checkpoints(self.engine, [
            {'event': 'UserPromptSubmit', 'harness': 'codex', 'session': 'sess_edit_after', 'at': later},
            {'event': 'PostToolUse', 'harness': 'codex', 'session': 'sess_edit_after', 'at': later + 10},
            {'event': 'Stop', 'harness': 'codex', 'session': 'sess_edit_after', 'at': later + 20},
        ])
        self.engine.sync()

        with self.engine.store._connect() as db:
            cov = receipt_coverage(db, now=later + 30)
        gaps = json.loads((self.state / 'receipt-gaps.json').read_text(encoding='utf-8'))

        self.assertEqual((cov['session']['covered'], cov['session']['total'], cov['session']['ratio']), (1, 1, 1.0))
        self.assertEqual((cov['last_edit']['covered'], cov['last_edit']['total'], cov['last_edit']['missing'], cov['last_edit']['ratio']), (0, 1, 1, 0.0))
        self.assertEqual(gaps['potential_missing_receipts'], 1)
        self.assertEqual(gaps['checkpoints'][0]['scope'], 'after_last_edit')

    def test_editless_pure_qa_session_excluded_from_last_edit_denominator(self):
        t0 = time.time() - 60
        record_checkpoints(self.engine, [
            {'event': 'UserPromptSubmit', 'harness': 'claude', 'session': 'sess_with_edit', 'at': t0},
            {'event': 'PostToolUse', 'harness': 'claude', 'session': 'sess_with_edit', 'at': t0 + 5},
            {'event': 'Stop', 'harness': 'claude', 'session': 'sess_with_edit', 'at': t0 + 20},
            {'event': 'UserPromptSubmit', 'harness': 'claude', 'session': 'sess_pure_qa', 'at': t0},
            {'event': 'Stop', 'harness': 'claude', 'session': 'sess_pure_qa', 'at': t0 + 10},
        ])
        self.engine.receipt('rc-with-edit', 'Edited file.', ['notes/work.md'], 'claude', session='sess_with_edit')
        self.engine.sync()

        with self.engine.store._connect() as db:
            cov = receipt_coverage(db, now=time.time() + 10)

        self.assertEqual((cov['session']['covered'], cov['session']['total']), (1, 2))
        self.assertEqual((cov['last_edit']['covered'], cov['last_edit']['total'], cov['last_edit']['missing'], cov['last_edit']['ratio']), (1, 1, 0, 1.0))

    def test_antigravity_uuid_receipt_matches_sha256_checkpoint_digest(self):
        raw_uuid = '12345678-1234-4321-abcd-1234567890ab'
        digest = hashlib.sha256(raw_uuid.encode()).hexdigest()[:24]

        self.state.mkdir(parents=True, exist_ok=True)
        hook.enqueue_event(
            self.vault,
            self.state,
            {'hook_event_name': 'SessionStart', 'session_id': raw_uuid, 'prompt': 'synthetic start', 'event_id': 'ag-start'},
            'antigravity',
        )
        hook.enqueue_event(
            self.vault,
            self.state,
            {'hook_event_name': 'Stop', 'session_id': raw_uuid, 'event_id': 'ag-stop'},
            'antigravity',
        )
        self.assertEqual(hook.drain_queue(self.vault, self.state)['processed'], 2)

        self.engine.receipt('rc-ag', 'Antigravity receipt with raw UUID.', ['notes/work.md'], 'antigravity', session=raw_uuid)
        # Same UUID on a different harness must never match Antigravity's checkpoint.
        self.engine.receipt('rc-codex-other', 'Other harness.', ['notes/work.md'], 'codex', session='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
        self.engine.sync()

        with self.engine.store._connect() as db:
            latest = _latest_receipts(db)
            self.assertIn(('antigravity', raw_uuid), latest)
            self.assertIn(('antigravity', digest), latest)
            cov = receipt_coverage(db, now=time.time() + 5)

        gaps = json.loads((self.state / 'receipt-gaps.json').read_text(encoding='utf-8'))
        self.assertEqual((cov['session']['covered'], cov['session']['total'], cov['session']['ratio']), (1, 1, 1.0))
        self.assertEqual(cov['last_edit']['total'], 0)
        self.assertEqual(gaps['potential_missing_receipts'], 0)

    def test_promptless_sessions_excluded_from_both_denominators_and_gaps(self):
        t0 = time.time() - 60
        record_checkpoints(self.engine, [
            {'event': 'SessionStart', 'harness': 'claude', 'session': 'no_prompt_edit', 'at': t0},
            {'event': 'PostToolUse', 'harness': 'claude', 'session': 'no_prompt_edit', 'at': t0 + 2},
            {'event': 'Stop', 'harness': 'claude', 'session': 'no_prompt_edit', 'at': t0 + 5},
            {'event': 'Stop', 'harness': 'codex', 'session': 'stop_only', 'at': t0 + 5},
        ])
        self.engine.sync()

        with self.engine.store._connect() as db:
            cov = receipt_coverage(db, now=time.time() + 10)
        gaps = json.loads((self.state / 'receipt-gaps.json').read_text(encoding='utf-8'))

        self.assertEqual(cov['total'], 0)
        self.assertIsNone(cov['ratio'])
        self.assertEqual(cov['last_edit']['total'], 0)
        self.assertIsNone(cov['last_edit']['ratio'])
        self.assertEqual(gaps['potential_missing_receipts'], 0)
        self.assertEqual(gaps['checkpoints'], [])

    def test_doctor_json_and_human_output_report_both_metrics(self):
        t0 = time.time() - 100
        # 1) Prompted + edit + receipt + trailing Q&A -> covered in both
        record_checkpoints(self.engine, [
            {'event': 'UserPromptSubmit', 'harness': 'claude', 'session': 's_ok', 'at': t0},
            {'event': 'PostToolUse', 'harness': 'claude', 'session': 's_ok', 'at': t0 + 5},
        ])
        self.engine.receipt('rc-ok', 'Covered edit.', ['notes/work.md'], 'claude', session='s_ok')
        later = time.time() + 60
        record_checkpoints(self.engine, [
            {'event': 'UserPromptSubmit', 'harness': 'claude', 'session': 's_ok', 'at': later},
            {'event': 'Stop', 'harness': 'claude', 'session': 's_ok', 'at': later + 5},
        ])
        # 2) Prompted + receipt + later edit -> covered for session, missing for last_edit
        record_checkpoints(self.engine, [
            {'event': 'UserPromptSubmit', 'harness': 'codex', 'session': 's_miss_edit', 'at': t0},
        ])
        self.engine.receipt('rc-miss', 'Before edit.', ['notes/work.md'], 'codex', session='s_miss_edit')
        record_checkpoints(self.engine, [
            {'event': 'PostToolUse', 'harness': 'codex', 'session': 's_miss_edit', 'at': later + 10},
            {'event': 'Stop', 'harness': 'codex', 'session': 's_miss_edit', 'at': later + 20},
        ])
        self.engine.sync()

        doc = self._doctor_json()
        cov = doc['receipt_coverage']
        self.assertEqual((cov['covered'], cov['total']), (2, 2))
        self.assertEqual((cov['session']['covered'], cov['session']['total']), (2, 2))
        self.assertEqual((cov['last_edit']['covered'], cov['last_edit']['total'], cov['last_edit']['ratio']), (1, 2, 0.5))
        self.assertIn('meaning', cov)

        human = human_result(doc, 'doctor', '5.0.0')
        self.assertIn('Makbuz kapsami: %100 (2/2 oturum, son 7 gun: %100) | son duzenleme: %50 (1/2 duzenleyen, son 7 gun: %50)', human)

    def test_legacy_schema_backfills_edit_at_from_hook_done(self):
        t0 = time.time() - 60
        with self.engine.store._connect() as db:
            db.execute('DROP TABLE IF EXISTS receipt_checkpoints')
            db.execute('CREATE TABLE receipt_checkpoints(harness TEXT, session TEXT, at REAL, turn_at REAL DEFAULT 0, project TEXT, project_id TEXT, prompt_at REAL DEFAULT 0, PRIMARY KEY(harness,session))')
            db.execute("INSERT INTO receipt_checkpoints VALUES ('claude', 'migrated_edit', ?, ?, 'demo', 'pid1', ?)", (t0 + 20, t0, t0))
        done_dir = self.state / 'hook-done'
        done_dir.mkdir(parents=True, exist_ok=True)
        (done_dir / 'edit1.json').write_text(json.dumps({
            'event': 'PostToolUse', 'harness': 'claude', 'session': 'migrated_edit', 'at': t0 + 10,
        }), encoding='utf-8')
        (done_dir / 'corrupt.json').write_text('{not valid json', encoding='utf-8')

        with self.engine.store._connect() as db:
            _checkpoint_schema(db)
            cov = receipt_coverage(db, now=time.time())

        self.assertEqual((cov['last_edit']['total'], cov['last_edit']['missing']), (1, 1))

    def test_last_edit_time_windows_and_multiple_edits_use_max_edit_at(self):
        now = time.time()
        # 1) 40 days ago: edited + receipt (all_time only)
        record_checkpoints(self.engine, [
            {'event': 'UserPromptSubmit', 'harness': 'claude', 'session': 'old_edit', 'at': now - 40 * 86400},
            {'event': 'PostToolUse', 'harness': 'claude', 'session': 'old_edit', 'at': now - 40 * 86400 + 10},
            {'event': 'Stop', 'harness': 'claude', 'session': 'old_edit', 'at': now - 40 * 86400 + 20},
        ])
        self.engine.receipt('rc-old', 'Old edit.', ['notes/work.md'], 'claude', session='old_edit')
        # 2) 15 days ago: edit_1 -> receipt -> edit_2 (now-15d+300s > receipt written at now! Let's force created_at in DB cleanly for old/future comparison)
        # Use timestamps relative to now: receipt written at `now` covers edits up to `now`, misses edit at `now + 120`.
        record_checkpoints(self.engine, [
            {'event': 'UserPromptSubmit', 'harness': 'codex', 'session': 'mid_miss', 'at': now - 15 * 86400},
            {'event': 'PostToolUse', 'harness': 'codex', 'session': 'mid_miss', 'at': now - 15 * 86400 + 10},
            {'event': 'Stop', 'harness': 'codex', 'session': 'mid_miss', 'at': now - 15 * 86400 + 20},
            {'event': 'UserPromptSubmit', 'harness': 'claude', 'session': 'recent_qa_only', 'at': now - 2 * 86400},
            {'event': 'Stop', 'harness': 'claude', 'session': 'recent_qa_only', 'at': now - 2 * 86400 + 10},
            {'event': 'UserPromptSubmit', 'harness': 'claude', 'session': 'recent_edit_miss', 'at': now - 2 * 86400},
            {'event': 'PostToolUse', 'harness': 'claude', 'session': 'recent_edit_miss', 'at': now - 2 * 86400 + 10},
        ])
        self.engine.receipt('rc-between', 'First edit receipt.', ['notes/work.md'], 'claude', session='recent_edit_miss')
        record_checkpoints(self.engine, [
            {'event': 'PostToolUse', 'harness': 'claude', 'session': 'recent_edit_miss', 'at': now + 120},
            {'event': 'Stop', 'harness': 'claude', 'session': 'recent_edit_miss', 'at': now - 2 * 86400 + 30},
        ])
        self.engine.sync()

        with self.engine.store._connect() as db:
            cov = receipt_coverage(db, now=now + 200)

        # Pure Q&A recent session is in session denominator (last_7d=2), NOT in last_edit denominator (last_7d=1)
        self.assertEqual((cov['session']['total'], cov['session']['last_30d']['total'], cov['session']['last_7d']['total']), (4, 3, 2))
        self.assertEqual((cov['last_edit']['total'], cov['last_edit']['covered'], cov['last_edit']['missing']), (3, 1, 2))
        self.assertEqual((cov['last_edit']['last_30d']['total'], cov['last_edit']['last_30d']['covered']), (2, 0))
        self.assertEqual((cov['last_edit']['last_7d']['total'], cov['last_edit']['last_7d']['covered']), (1, 0))


if __name__ == '__main__':
    unittest.main()
