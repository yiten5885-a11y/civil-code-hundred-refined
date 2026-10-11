#!/usr/bin/env python3
"""Compare two official 2025 Marriage Registration Regulation snapshots.

This is a text-integrity check, not a legal-effect or applicability review.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE_IDS = ("marriage_registration_2025", "marriage_registration_moj")
EXPECTED_ARTICLES = 28


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(text: str) -> str:
    # The MOJ HTML uses ASCII parentheses where the MEE reprint uses full-width
    # parentheses. Do not erase other punctuation or substantive words.
    return re.sub(r"[\s\u3000]+", "", text.translate(str.maketrans("（）", "()")))


def compare(left: list[dict], right: list[dict]) -> list[int]:
    if ([article.get("number") for article in left] != list(range(1, EXPECTED_ARTICLES + 1))
        or [article.get("number") for article in right] != list(range(1, EXPECTED_ARTICLES + 1))):
        raise ValueError("两份条例索引的条号不完整或不连续")
    return [a["number"] for a, b in zip(left, right) if canonical(a["text"]) != canonical(b["text"])]


def audit(root: Path) -> dict:
    manifest = json.loads((root / "sources/SOURCE_MANIFEST.json").read_text())
    texts = []
    hashes = {}
    for source_id in SOURCE_IDS:
        entry = manifest[source_id]
        raw = root / "sources/raw" / f"{source_id}.html"
        index = root / "sources/normalized" / f"{source_id}.json"
        if (entry.get("raw_path") != str(raw.relative_to(root))
            or digest(raw) != entry.get("sha256")
            or digest(index) != entry.get("normalized_sha256")):
            raise ValueError(f"{source_id}: 原文或索引与来源清单不符")
        texts.append(json.loads(index.read_text()))
        hashes[source_id] = {"raw_sha256": entry["sha256"], "normalized_sha256": entry["normalized_sha256"]}
    differences = compare(*texts)
    return {"source_ids": list(SOURCE_IDS), "article_count": EXPECTED_ARTICLES,
            "normalized_differences": differences, "source_hashes": hashes,
            "text_integrity_pass": not differences, "legal_effect_review": "未完成",
            "legal_correctness_checked": False}


def main() -> None:
    result = audit(ROOT)
    path = ROOT / "reports/MARRIAGE_REGISTRATION_CROSSCHECK.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("article_count", "normalized_differences", "text_integrity_pass")}, ensure_ascii=False))
    if not result["text_integrity_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
