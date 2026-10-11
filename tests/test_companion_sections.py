"""Section headings in official HTML must not become the previous article's law text."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from normalize_companions import parse_source


class CompanionSectionTests(unittest.TestCase):
    def test_registered_heading_is_excluded_without_removing_article_items(self):
        html = "<p>第一条 这里是第一款内容。</p><p>二、合同的订立</p><p>第二条 这里是第二款内容。</p><p>（一）保留条内分项。</p>"
        articles, anomalies = parse_source(html, ("二、合同的订立",))
        self.assertEqual([a["number"] for a in articles], [1, 2])
        self.assertEqual(articles[0]["text"], "这里是第一款内容。")
        self.assertEqual(articles[1]["text"], "这里是第二款内容。\n（一）保留条内分项。")
        self.assertEqual(anomalies, [])


if __name__ == "__main__":
    unittest.main()
