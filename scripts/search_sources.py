#!/usr/bin/env python3
"""Search hash-verified local article indexes for reviewer evidence gathering.

Search hits are source pointers, never legal advice or applicability decisions.
The normalized texts are private local inputs and are not shipped in the skill.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = re.compile(r"[a-z0-9_]+\Z")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_articles(root: Path, source_id: str, entry: dict) -> list[dict]:
    if not SOURCE_ID.fullmatch(source_id):
        raise ValueError("来源编号格式无效")
    raw_value = entry.get("raw_path")
    raw_rel = Path(raw_value) if isinstance(raw_value, str) else Path()
    if (not isinstance(raw_value, str) or raw_rel.is_absolute() or ".." in raw_rel.parts
        or raw_rel.parts[:2] != ("sources", "raw")):
        raise ValueError(f"{source_id}: 原始路径无效")
    raw = root / raw_rel
    index = root / "sources/normalized" / f"{source_id}.json"
    if (not raw.is_file() or sha256(raw) != entry.get("sha256")
        or not index.is_file() or sha256(index) != entry.get("normalized_sha256")):
        raise ValueError(f"{source_id}: 来源快照或分条索引缺失、校验失败")
    try:
        articles = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{source_id}: 分条索引无法读取") from exc
    if not isinstance(articles, list) or not articles:
        raise ValueError(f"{source_id}: 分条索引为空或格式无效")
    seen = set()
    for article in articles:
        if (not isinstance(article, dict) or type(article.get("number")) is not int
            or article["number"] < 1 or article["number"] in seen
            or not isinstance(article.get("text"), str) or not article["text"].strip()
            or not isinstance(article.get("heading"), str)
            or article.get("sha256") != hashlib.sha256(re.sub(r"[\s\u3000]+", "", article["text"]).encode("utf-8")).hexdigest()):
            raise ValueError(f"{source_id}: 分条记录格式、条号或条文哈希无效")
        seen.add(article["number"])
    return articles


def search(root: Path, terms: list[str], source_ids: list[str], article_numbers: list[int], limit: int = 20) -> dict:
    if limit < 1 or limit > 100:
        raise ValueError("结果上限须在 1 至 100 之间")
    terms = [term.strip() for term in terms]
    if any(not term for term in terms) or not terms and not article_numbers:
        raise ValueError("请指定非空检索词或条号")
    if any(type(number) is not int or number < 1 for number in article_numbers):
        raise ValueError("条号须为正整数")
    try:
        manifest = json.loads((root / "sources/SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("来源清单无法读取") from exc
    if not isinstance(manifest, dict):
        raise ValueError("来源清单格式无效")
    selected = source_ids or sorted(key for key, value in manifest.items()
                                    if isinstance(value, dict) and value.get("normalized_sha256"))
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("来源选择为空或重复")
    hits = []
    for source_id in selected:
        entry = manifest.get(source_id)
        if not isinstance(entry, dict) or not entry.get("normalized_sha256"):
            raise ValueError(f"{source_id}: 不存在可检索的分条索引")
        articles = verified_articles(root, source_id, entry)
        for article in articles:
            if article_numbers and article["number"] not in article_numbers:
                continue
            matched_terms = [term for term in terms if term in article["text"]]
            if terms and not matched_terms:
                continue
            hits.append({
                "source_id": source_id,
                "source_title": entry.get("title"),
                "source_url": entry.get("url"),
                "source_snapshot_sha256": entry["sha256"],
                "normalized_index_sha256": entry["normalized_sha256"],
                "effect_status": entry.get("effect_status"),
                "effective_on": entry.get("effective_on"),
                "article": article["number"],
                "heading": article["heading"],
                "outline": ({key: article.get(key) for key in
                             ("book_heading", "division_heading", "chapter_heading", "section_heading", "appendix")}
                            if article.get("book_heading") else None),
                "article_sha256": article["sha256"],
                "text": article["text"],
                "matched_terms": matched_terms,
            })
    hits.sort(key=lambda hit: (-len(hit["matched_terms"]), hit["source_id"], hit["article"]))
    return {
        "status": "仅供资料排查；效力、解释和个案适用待法律专业复核",
        "selected_sources": selected,
        "terms": terms,
        "article_numbers": article_numbers,
        "total_matches": len(hits),
        "truncated": len(hits) > limit,
        "hits": hits[:limit],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--term", action="append", default=[], help="可重复；多个词按任一命中检索")
    parser.add_argument("--source", action="append", default=[], help="来源编号，可重复；默认全部已建索引来源")
    parser.add_argument("--article", type=int, action="append", default=[], help="条号，可重复")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    try:
        result = search(ROOT, args.term, args.source, args.article, args.limit)
    except ValueError as exc:
        parser.exit(2, f"检索中止：{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
