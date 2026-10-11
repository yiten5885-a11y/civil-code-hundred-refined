"""Civil Code article pointers retain the source's changing outline context."""
from pathlib import Path
import tempfile
import unittest

from scripts.source_pipeline import parse


class CivilCodeOutlineTests(unittest.TestCase):
    def test_article_outline_resets_at_chapter_and_appendix(self):
        source = """<DIV id="BodyLabel">
        <p>第七编 目录提示</p>
        <p>第一编 总则</p><p>第一章 基本规定</p>
        <p>第一条 第一条正文。</p>
        <p>第一节 一般规定</p><p>第二条 第二条正文。</p>
        <p>第二章 下一章</p><p>第三条 第三条正文。</p>
        <p>附 则</p><p>第四条 第四条正文。</p>
        </DIV>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.html"
            path.write_text(source, encoding="utf-8")
            articles, anomalies = parse(path, True)
        self.assertEqual(anomalies, [])
        self.assertEqual([a["book"] for a in articles], [1] * 4)
        self.assertEqual(articles[0]["chapter_heading"], "第一章 基本规定")
        self.assertEqual(articles[1]["section_heading"], "第一节 一般规定")
        self.assertEqual(articles[2]["chapter_heading"], "第二章 下一章")
        self.assertIsNone(articles[2]["section_heading"])
        self.assertIsNone(articles[3]["chapter_heading"])
        self.assertTrue(articles[3]["appendix"])
        self.assertEqual([a["text"] for a in articles],
                         ["第一条正文。", "第二条正文。", "第三条正文。", "第四条正文。"])


if __name__ == "__main__":
    unittest.main()
