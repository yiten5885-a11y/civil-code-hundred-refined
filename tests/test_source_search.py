"""A reviewer search must not return unverified or ambiguous source text."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("search_sources", PROJECT / "scripts/search_sources.py")
search_sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search_sources)


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class SourceSearchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "sources/raw").mkdir(parents=True)
        (self.root / "sources/normalized").mkdir(parents=True)
        self.raw = self.root / "sources/raw/example.html"
        self.raw.write_text("官方页面样本", encoding="utf-8")
        articles = [
            {"number": 1, "heading": "第一条", "text": "押金返还时间", "sha256": sha("押金返还时间".encode()),
             "book_heading": "第一编 总则", "division_heading": None,
             "chapter_heading": "第一章 基本规定", "section_heading": None, "appendix": False},
            {"number": 2, "heading": "第二条", "text": "其他内容", "sha256": sha("其他内容".encode())},
        ]
        self.index = self.root / "sources/normalized/example.json"
        self.index.write_text(json.dumps(articles, ensure_ascii=False), encoding="utf-8")
        self.manifest = self.root / "sources/SOURCE_MANIFEST.json"
        self.manifest.write_text(json.dumps({"example": {
            "title": "样本", "url": "https://example.invalid/source",
            "raw_path": "sources/raw/example.html", "sha256": sha(self.raw.read_bytes()),
            "normalized_sha256": sha(self.index.read_bytes()), "effect_status": "待逐项核验",
        }}, ensure_ascii=False), encoding="utf-8")

    def test_search_returns_hash_bound_pointer_and_text(self):
        result = search_sources.search(self.root, ["押金"], [], [], 20)
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["hits"][0]["article"], 1)
        self.assertEqual(result["hits"][0]["matched_terms"], ["押金"])
        self.assertEqual(result["hits"][0]["effect_status"], "待逐项核验")
        self.assertEqual(result["hits"][0]["outline"]["chapter_heading"], "第一章 基本规定")
        self.assertNotIn("已审核", result["status"])

    def test_changed_snapshot_stops_search(self):
        self.raw.write_text("已被改动", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "校验失败"):
            search_sources.search(self.root, ["押金"], [], [], 20)

    def test_changed_index_stops_search(self):
        self.index.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "校验失败"):
            search_sources.search(self.root, [], ["example"], [1], 20)


if __name__ == "__main__":
    unittest.main()
