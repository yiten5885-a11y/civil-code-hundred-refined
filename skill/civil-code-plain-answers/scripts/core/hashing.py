"""确定性摘要计算。

规格 5：
- 采用 UTF-8、键排序和固定 JSON 序列化；
- 规则的语义摘要只覆盖语义字段，排除摘要自身、审核引用和运行时间；
- 模型不能提供摘要代替程序计算。
"""

from __future__ import annotations

import hashlib
from typing import Any

RULE_SEMANTIC_FIELDS = (
    "scenario_id",
    "capability_ids",
    "source_refs",
    "scope_predicates",
    "required_facts",
    "predicates",
    "dependencies",
    "allowed_template_ids",
    "prohibited_inferences",
    "unknown_policy",
    "conflict_policy",
)

TEMPLATE_SEMANTIC_FIELDS = (
    "kind",
    "text",
    "slots",
    "required_predicates",
    "source_refs",
)


def canonical_json(obj: Any) -> bytes:
    """固定序列化：键排序、紧凑分隔符、UTF-8，不做兼容归一化。"""
    import json

    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_hex(text.encode("utf-8"))


def semantic_sha256(record: dict, fields: tuple[str, ...]) -> str:
    subset = {k: record.get(k) for k in fields}
    return sha256_hex(canonical_json(subset))


def rule_semantic_sha256(rule: dict) -> str:
    return semantic_sha256(rule, RULE_SEMANTIC_FIELDS)


def template_semantic_sha256(template: dict) -> str:
    return semantic_sha256(template, TEMPLATE_SEMANTIC_FIELDS)


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
