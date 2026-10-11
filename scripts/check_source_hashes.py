#!/usr/bin/env python3
"""Audit every local source snapshot and normalized index against the manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(root: Path) -> dict:
    manifest = json.loads((root / "sources/SOURCE_MANIFEST.json").read_text())
    issues = []
    raw_verified = normalized_verified = 0
    if not isinstance(manifest, dict) or not manifest:
        issues.append("来源清单为空或格式不符")
        manifest = {}
    for source_id, entry in manifest.items():
        if not isinstance(source_id, str) or not source_id.replace("_", "").isalnum() or not isinstance(entry, dict):
            issues.append(f"{source_id}: 来源条目格式无效")
            continue
        raw_value = entry.get("raw_path")
        raw_rel = Path(raw_value) if isinstance(raw_value, str) else Path()
        if (not isinstance(raw_value, str) or raw_rel.is_absolute() or ".." in raw_rel.parts
            or raw_rel.parts[:2] != ("sources", "raw")
            or not entry.get("sha256")):
            issues.append(f"{source_id}: 原始路径或哈希缺失")
        else:
            raw = root / raw_rel
            if not raw.is_file() or sha(raw) != entry["sha256"]:
                issues.append(f"{source_id}: 原始快照缺失或哈希不符")
            else:
                raw_verified += 1
        if "normalized_sha256" in entry:
            normalized = root / "sources/normalized" / f"{source_id}.json"
            if not normalized.is_file() or sha(normalized) != entry["normalized_sha256"]:
                issues.append(f"{source_id}: 规范化索引缺失或哈希不符")
            else:
                normalized_verified += 1
    return {"source_entries": len(manifest), "raw_verified": raw_verified,
            "normalized_verified": normalized_verified, "issues": issues,
            "hash_audit_pass": not issues, "legal_effect_review": "未完成",
            "legal_correctness_checked": False}


def main() -> None:
    report = audit(ROOT)
    target = ROOT / "reports/SOURCE_HASH_AUDIT.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("source_entries", "raw_verified", "normalized_verified", "hash_audit_pass")}, ensure_ascii=False))
    if not report["hash_audit_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
