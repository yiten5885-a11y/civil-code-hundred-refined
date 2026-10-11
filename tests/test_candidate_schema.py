"""Candidate citations may be normalized only from exact article labels."""
import importlib.util
from pathlib import Path
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
spec = importlib.util.spec_from_file_location("candidate", PROJECT / "scripts/generate_one_candidate.py")
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class CitationTests(unittest.TestCase):
    def test_exact_labels(self):
        self.assertEqual(candidate.citation_number(703), 703)
        self.assertEqual(candidate.citation_number("民法典第703条"), 703)
        self.assertEqual(candidate.citation_number("第733条"), 733)

    def test_ambiguous_labels_rejected(self):
        for value in (True, "第703条及第733条", "703", "民法典第703条另见合同", "第七百零三条"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                candidate.citation_number(value)


if __name__ == "__main__":
    unittest.main()
