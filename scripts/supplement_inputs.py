"""Validate explicit, provisional multi-source inputs for private Qwen drafts."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re

from generate_one_candidate import ARTICLES

ROOT = Path(__file__).resolve().parents[1]
REF_ID = re.compile(r"[a-z0-9_]+\Z")


def ref_key(ref: dict) -> tuple[str, int]:
    if (not isinstance(ref, dict) or set(ref) != {"source_id", "article"}
        or not isinstance(ref["source_id"], str) or not REF_ID.fullmatch(ref["source_id"])
        or type(ref["article"]) is not int or ref["article"] < 1):
        raise ValueError("来源选择需为 source_id 与正整数 article")
    return ref["source_id"], ref["article"]


def spec_sha256(spec: dict) -> str:
    """Bind one scene without invalidating other scenes when the plan expands."""
    data = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def load_specs(root: Path = ROOT) -> dict:
    path = root / "plan/SUPPLEMENT_EVIDENCE.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("多来源候选输入清单无法读取") from exc
    scenarios = document.get("scenarios") if isinstance(document, dict) else None
    if not isinstance(scenarios, dict) or not scenarios:
        raise ValueError("多来源候选输入清单为空或格式无效")
    for scene, spec in scenarios.items():
        if scene not in ARTICLES or not isinstance(spec, dict):
            raise ValueError(f"{scene}: 场景编号或输入配置无效")
        if not isinstance(spec.get("focus"), str) or not spec["focus"].strip():
            raise ValueError(f"{scene}: 缺少问题焦点")
        evidence = spec.get("evidence")
        required = spec.get("required_citations")
        if not isinstance(evidence, list) or not evidence or not isinstance(required, list) or not required:
            raise ValueError(f"{scene}: 输入依据或必引条文缺失")
        keys = [ref_key(ref) for ref in evidence]
        required_keys = [ref_key(ref) for ref in required]
        if (len(keys) != len(set(keys)) or len(required_keys) != len(set(required_keys))
            or not set(required_keys).issubset(keys)):
            raise ValueError(f"{scene}: 依据重复或必引条文不在输入中")
    return scenarios
