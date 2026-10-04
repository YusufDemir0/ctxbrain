"""The agent install guide stays deterministic, novice-safe and points at ctxbrain only."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicEntryTest(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / 'beyin.md').read_text(encoding='utf-8')

    def test_entrypoint_installs_ctxbrain_and_preserves_notes(self):
        for phrase in ('YusufDemir0/ctxbrain', 'install_v3.py" --vault', '--plan', 'beyin.py doctor',
                       'notlarini silme', '.agents/skills/beyin/SKILL.md', 'ctx: liste'):
            self.assertIn(phrase, self.text)
        self.assertNotIn('git reset --hard', self.text)
        self.assertNotIn('avenox.lol', self.text)
        self.assertNotIn('avenoxai/avenoxbeyin/releases', self.text)

    def test_entrypoint_requires_fresh_session_before_memory_success_claim(self):
        self.assertIn('Yeni bir oturum', self.text)
        self.assertIn('"dogrulandi" deme', self.text)


if __name__ == '__main__':
    unittest.main()
