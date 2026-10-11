#!/usr/bin/env python3
"""Verify private candidate supplements bind to the supplied local source text.

This checks structure and hashes, never legal meaning or reviewer identity.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from generate_evidence_supplement import (prompt_for, selected_evidence,
                                          known_error_codes,
                                          third_turn_correction_binding,
                                          third_turn_correction_signal,
                                          uncited_article_mentions)
from search_sources import verified_articles
from supplement_inputs import load_specs, ref_key, spec_sha256

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_one(scene: str, spec: dict, manifest: dict, manifest_path: Path) -> dict:
    path = ROOT / "rules/candidates/supplements" / f"{scene}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    card = record["card"]
    manifest_changed = record.get("source_manifest_sha256") != sha(manifest_path)
    if (record.get("scene") != scene or record.get("status") != "candidate_unreviewed"
        or not isinstance(record.get("source_manifest_sha256"), str)
        or ("evidence_selection_sha256" in record and record["evidence_selection_sha256"] != spec_sha256(spec))
        or record.get("prior_candidate_sha256") != sha(ROOT / "rules/candidates" / f"{scene}.json")
        or json.loads(record["raw_content"]) != card):
        raise ValueError(f"{scene}: 候选状态、来源清单、旧稿或模型原文绑定不符")

    expected_refs = {ref_key(ref) for ref in spec["evidence"]}
    required_refs = {ref_key(ref) for ref in spec["required_citations"]}
    actual_refs = set()
    indexes = {}
    for item in record.get("input_evidence", []):
        if not isinstance(item, dict) or type(item.get("article")) is not int:
            raise ValueError(f"{scene}: 输入来源格式无效")
        key = (item.get("source_id"), item["article"])
        if key not in expected_refs or key in actual_refs:
            raise ValueError(f"{scene}: 输入来源超界或重复")
        source_id, number = key
        if source_id not in indexes:
            entry = manifest.get(source_id)
            if not isinstance(entry, dict):
                raise ValueError(f"{scene}: 来源编号不在清单")
            indexes[source_id] = verified_articles(ROOT, source_id, entry)
        articles = [x for x in indexes[source_id] if x["number"] == number]
        if len(articles) != 1 or item.get("article_sha256") != articles[0].get("sha256"):
            raise ValueError(f"{scene}: 输入条文哈希不符")
        actual_refs.add(key)
    if actual_refs != expected_refs:
        raise ValueError(f"{scene}: 输入条文缺失")
    if "evidence_selection_sha256" in record:
        evidence, prior, _ = selected_evidence(ROOT, scene, spec)
        version = record.get("prompt_version", 1)
        if version not in (1, 2, 3):
            raise ValueError(f"{scene}: 提示词版本无效")
        prompt = prompt_for(scene, spec["focus"], prior["card"]["plain_explanation"], evidence,
                            spec["required_citations"] if version >= 2 else None,
                            require_correction_binding=version >= 3)
        if record.get("prompt_sha256") != hashlib.sha256(prompt.encode("utf-8")).hexdigest():
            raise ValueError(f"{scene}: 提示词与当前证据选择不符")

    citations = card.get("cited_sources")
    if (not isinstance(citations, list) or not citations
        or any(not isinstance(ref, dict) or type(ref.get("article")) is not int
               or (ref.get("source_id"), ref["article"]) not in expected_refs for ref in citations)
        or not required_refs.issubset({(ref["source_id"], ref["article"]) for ref in citations})):
        raise ValueError(f"{scene}: 候选引用超出所给来源")
    dialogue = card.get("dialogue")
    if (not isinstance(dialogue, list) or len(dialogue) != 3
        or any(not isinstance(turn, dict) or not isinstance(turn.get("user"), str)
               or not isinstance(turn.get("assistant"), str) for turn in dialogue)):
        raise ValueError(f"{scene}: 三轮示例结构无效")
    missing_mentions = uncited_article_mentions(card)
    correction_signal = third_turn_correction_signal(card)
    correction_binding = third_turn_correction_binding(card)
    known_errors = known_error_codes(card, scene)
    return {"candidate_sha256": sha(path), "input_article_count": len(actual_refs),
            "citation_count": len(citations), "structure_pass": not missing_mentions and correction_signal and correction_binding,
            "known_error_codes": known_errors, "known_error_screen_pass": not known_errors,
            "uncited_article_mentions": missing_mentions,
            "third_turn_correction_signal": correction_signal,
            "third_turn_correction_binding": correction_binding,
            "source_manifest_changed_after_generation": manifest_changed,
            "manifest_change_review": "须复核新增或变更来源对本场景的影响" if manifest_changed else "无",
            "prompt_binding": "已重算输入选择与提示词哈希" if "evidence_selection_sha256" in record else "旧稿仅核对输入条文；原提示词未重算",
            "legal_correctness_checked": False, "professional_review": "未完成"}


def main() -> None:
    manifest_path = ROOT / "sources/SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    specs = load_specs(ROOT)
    extra = {path.stem for path in (ROOT / "rules/candidates/supplements").glob("*.json")} - set(specs)
    if extra:
        raise ValueError(f"存在未登记输入依据的补充候选：{sorted(extra)}")
    report = {"status": "未获法律专业复核", "supplements": {
        scene: audit_one(scene, spec, manifest, manifest_path)
        for scene, spec in specs.items()
    }}
    out = ROOT / "reports/SUPPLEMENT_AUDIT.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
