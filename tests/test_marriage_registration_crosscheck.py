"""The text comparison tolerates typography but stops at real differences."""
import importlib.util
from pathlib import Path
import unittest

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("crosscheck_marriage_registration", PROJECT / "scripts/crosscheck_marriage_registration.py")
crosscheck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crosscheck)


class MarriageRegistrationCrosscheckTests(unittest.TestCase):
    def test_typographic_parentheses_do_not_hide_substantive_change(self):
        left = [{"number": n, "text": f"第{n}项（申请）"} for n in range(1, 29)]
        right = [{"number": n, "text": f"第{n}项(申请)"} for n in range(1, 29)]
        self.assertEqual(crosscheck.compare(left, right), [])
        right[15]["text"] = "第16项(登记)"
        self.assertEqual(crosscheck.compare(left, right), [16])

    def test_missing_article_stops_comparison(self):
        articles = [{"number": n, "text": "正文"} for n in range(1, 29)]
        with self.assertRaises(ValueError):
            crosscheck.compare(articles, articles[:-1])


if __name__ == "__main__":
    unittest.main()
