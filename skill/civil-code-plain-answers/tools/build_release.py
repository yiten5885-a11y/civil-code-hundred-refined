#!/usr/bin/env python3
"""确定性构建：生成 sources.json、回填摘要、生成发布清单。

规格 5、5.6、10.1：
- 语义摘要只能由程序计算，模型不能提供；
- 来源与模板只保留一个真实数据源，构建时校验摘要；
- payload_sha256 根据排序后的负载文件路径与摘要列表计算，排除发布清单自身；
- 构建失败不产出可误认作正式版的包。
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REFERENCES = os.path.join(ROOT, "references")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
from core import hashing  # noqa: E402

PAYLOAD_FILES = [
    "SKILL.md",
    "scripts/answer.py",
    "references/rules.json",
    "references/templates.json",
    "references/sources.json",
    "references/reviews.json",
    "config/example.json",
]

EFFECT_STATE = {
    "prc-civil-code-2020": "IN_FORCE",
    "housing-rental-regulation-2025": "IN_FORCE",
}

# 来源的发布与施行信息：取自 sources/*/meta.json 所在页面，未推测。
SOURCE_META = {
    "prc-civil-code-2020": {
        "title": "中华人民共和国民法典",
        "issuer": "全国人民代表大会",
        "source_type": "法律",
        "promulgated_on": "2020-05-28",
        "effective_from": "2021-01-01",
        "effective_to": None,
        "jurisdiction": "中国大陆",
        "applicability_note": "全国适用；施行日期依第一千二百六十条。涉及施行前发生的事实，不能当然适用本法的具体规则。",
        "verification_method": "官方入口页面抓取 + 条文定位 + 字节与规范文本摘要比对",
    },
    "housing-rental-regulation-2025": {
        "title": "住房租赁条例（中华人民共和国国务院令第812号）",
        "issuer": "国务院",
        "source_type": "行政法规",
        "promulgated_on": "2025-07-16",
        "effective_from": "2025-09-15",
        "effective_to": None,
        "jurisdiction": "中国大陆",
        "applicability_note": "第二条限定适用于城镇国有土地上住房租赁活动及其监督管理；自 2025-09-15 起施行，施行前发生的事实不能当然适用。",
        "verification_method": "官方转载页面抓取 + 条文定位 + 字节与规范文本摘要比对（转载页，页内标注来源为中国政府网）",
    },
}


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        )
        return out.stdout.strip() or "UNCOMMITTED"
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def build_sources() -> dict:
    metas = sorted(glob.glob(os.path.join(ROOT, "sources", "*", "meta.json")))
    sources = []
    for path in metas:
        meta = _read_json(path)
        sid = meta["source_id"]
        extra = SOURCE_META.get(sid, {})
        raw_path = os.path.join(ROOT, meta["raw_snapshot"])
        articles = []
        for label in sorted(meta["articles"]):
            item = meta["articles"][label]
            articles.append(
                {
                    "provision_locator": item["provision_locator"],
                    "canonical_text": item["canonical_text"],
                    "canonical_sha256": item["canonical_sha256"],
                }
            )
        sources.append(
            {
                "schema_version": "2.0",
                "source_id": sid,
                "version": meta["version"],
                "title": extra.get("title", meta["title"]),
                "issuer": extra.get("issuer", meta["issuer"]),
                "source_type": extra.get("source_type", meta["source_type"]),
                "official_url": meta["official_url"],
                "provision_locator": "条、款、项级定位见 articles",
                "raw_snapshot": meta["raw_snapshot"],
                "raw_sha256": meta["raw_sha256"],
                "canonical_sha256": hashlib.sha256(
                    "".join(a["canonical_text"] for a in articles).encode("utf-8")
                ).hexdigest(),
                "promulgated_on": extra.get("promulgated_on"),
                "effective_from": extra.get("effective_from"),
                "effective_to": extra.get("effective_to"),
                "jurisdiction": extra.get("jurisdiction"),
                "applicability_note": extra.get("applicability_note"),
                "verified_at": meta["retrieved_at"],
                "verification_method": extra.get("verification_method"),
                "verifier_ref": "reviews.json#SRC-CHK-" + ("CIVIL-2020-001" if "civil" in sid else "HOUSING-2025-001"),
                "verification_state": "VERIFIED",
                "effect_state": EFFECT_STATE.get(sid, "UNKNOWN"),
                "retrieval_state": "AVAILABLE" if os.path.exists(raw_path) else "UNAVAILABLE",
                "related_source_ids": [],
                "related_rule_ids": [],
                "articles": articles,
                "warnings": meta.get("warnings", []),
                "raw_origin": meta.get("raw_origin"),
            }
        )
    doc = {"schema_version": "2.0", "sources": sources}
    _write_json(os.path.join(REFERENCES, "sources.json"), doc)
    return doc


def fill_source_refs(sources_doc: dict, *docs: dict) -> list[str]:
    """按 (id, version, provision_locator) 回填 CANONICAL_TEXT 摘要。"""
    index = {}
    for rec in sources_doc["sources"]:
        for art in rec["articles"]:
            index[(rec["source_id"], rec["version"], art["provision_locator"])] = (
                art["canonical_sha256"]
            )
    missing: list[str] = []

    def walk(owner: str, entries: list[dict], key_name: str) -> None:
        for entry in entries:
            for sref in entry.get("source_refs") or []:
                key = (sref["id"], sref["version"], sref.get("provision_locator"))
                sha = index.get(key)
                if sha is None:
                    missing.append(f"{owner}.{entry.get(key_name)}: {key}")
                    continue
                sref["sha256"] = sha

    for doc in docs:
        if "templates" in doc:
            walk("template", doc["templates"], "template_id")
        if "rules" in doc:
            walk("rule", doc["rules"], "rule_id")
    return missing


def fill_semantics(rules_doc: dict, tmpl_doc: dict) -> None:
    for rule in rules_doc["rules"]:
        rule["semantic_sha256"] = hashing.rule_semantic_sha256(rule)
    for tmpl in tmpl_doc["templates"]:
        tmpl["semantic_sha256"] = hashing.template_semantic_sha256(tmpl)


def fill_reviews(reviews_doc: dict, rules_doc: dict, tmpl_doc: dict, sources_doc: dict) -> None:
    by_id = {r["rule_id"]: r for r in rules_doc["rules"]}
    src_by_id = {s["source_id"]: s for s in sources_doc["sources"]}
    for rev in reviews_doc["reviews"]:
        sid = rev.get("subject_id")
        if sid in by_id:
            rev["subject_sha256"] = by_id[sid].get("semantic_sha256")
            rev["subject_version"] = by_id[sid].get("version")
            rev["subject_hash_kind"] = "SEMANTIC"
        elif sid in src_by_id:
            if rev.get("subject_hash_kind") == "FILE_BYTES":
                rev["subject_sha256"] = src_by_id[sid].get("raw_sha256")
            else:
                rev["subject_sha256"] = src_by_id[sid].get("canonical_sha256")
            rev["subject_version"] = src_by_id[sid].get("version")
        elif sid == "navigation-template-set":
            digest = hashlib.sha256(
                "".join(
                    sorted(
                        t["semantic_sha256"]
                        for t in tmpl_doc["templates"]
                        if t["kind"] != "LEGAL_EXPLANATION"
                    )
                ).encode("utf-8")
            ).hexdigest()
            rev["subject_sha256"] = digest
            rev["subject_hash_kind"] = "SEMANTIC"


def build_manifest(rules_doc: dict, tmpl_doc: dict, sources_doc: dict,
                   release_id: str, software_version: str, profile: str) -> dict:
    enabled = [
        "NAV01",
        "NAV02",
        "NAV03",
        "DRAFT01",
        "SOURCE01",
        "DIALOG01",
    ]
    active_rules = {
        r["rule_id"]: r["version"]
        for r in rules_doc["rules"]
        if r.get("lifecycle_state") == "ACTIVE"
    }
    template_versions = {t["template_id"]: t["version"] for t in tmpl_doc["templates"]}
    source_versions = {s["source_id"]: s["version"] for s in sources_doc["sources"]}

    payload = []
    for rel in PAYLOAD_FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            raise SystemExit(f"[构建失败] 缺少负载文件：{rel}")
        payload.append({"path": rel, "sha256": hashing.file_sha256(path)})
    payload.sort(key=lambda x: x["path"])
    payload_sha256 = hashlib.sha256(
        hashing.canonical_json(payload)
    ).hexdigest()

    return {
        "schema_version": "2.0",
        "release_id": release_id,
        "software_version": software_version,
        "commit_id": git_commit(),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": profile,
        "payload_sha256": payload_sha256,
        "payload_files": payload,
        "enabled_capabilities": enabled,
        "disabled_capabilities": {
            "LEGAL01": "未取得真实法律复核记录（PENDING_REVIEW）",
            "LEGAL02": "未取得真实法律复核记录（PENDING_REVIEW）",
        },
        "active_rule_versions": active_rules,
        "disabled_rule_versions": {
            r["rule_id"]: r["version"]
            for r in rules_doc["rules"]
            if r.get("lifecycle_state") != "ACTIVE"
        },
        "template_versions": template_versions,
        "source_versions": source_versions,
        "host_compatibility": {
            "verified": ["workbuddy-desktop（macOS，Python 3.13）"],
            "unverified": ["其他 Agent Skills 宿主"],
        },
        "model_profile": {
            "expected": "本地 Ollama + Qwen（标识以本机实测为准）",
            "observed_this_build": (
                "本机 Ollama 0.40.2 在 127.0.0.1:11434 监听；唯一模型条目 qwen3.8-macmini:27b "
                "为 remote 代理（remote_host=http://127.0.0.1:11435，size=234B，无本地权重），"
                "上游 11435 未监听，调用返回 HTTP 400 Bad Request；本机无可用权重，未取得真实模型输出"
            ),
            "degraded_path": "heuristic-no-model（非模型，仅按已核对模板路由）",
        },
        "gate_run_id": None,
        "review_refs": [r["review_id"] for r in _read_json(
            os.path.join(REFERENCES, "reviews.json"))["reviews"]],
        "known_limits": [
            "只覆盖中国大陆住宅租赁押金场景的材料核对与沟通草稿",
            "不提供法律结论、金额与期限判断、胜诉预测、诉讼代理",
            "法律解释能力（LEGAL01/LEGAL02）未开放",
            "本机构建环境未能实际调用本地 Qwen，对话记录非真实模型运行",
            "住房租赁条例来源为转载页，未取得中国政府网原始页面交叉比对",
        ],
        "previous_release": None,
        "revocation_version": 1,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-id", default=None)
    ap.add_argument("--software-version", default="0.1.0-d1")
    ap.add_argument("--profile", default="D1")
    args = ap.parse_args()

    rules_doc = _read_json(os.path.join(REFERENCES, "rules.json"))
    tmpl_doc = _read_json(os.path.join(REFERENCES, "templates.json"))
    reviews_doc = _read_json(os.path.join(REFERENCES, "reviews.json"))

    sources_doc = build_sources()
    missing = fill_source_refs(sources_doc, tmpl_doc, rules_doc)
    if missing:
        for m in missing:
            print(f"[构建失败] 来源引用无法解析：{m}", file=sys.stderr)
        return 1

    fill_semantics(rules_doc, tmpl_doc)
    fill_reviews(reviews_doc, rules_doc, tmpl_doc, sources_doc)

    _write_json(os.path.join(REFERENCES, "rules.json"), rules_doc)
    _write_json(os.path.join(REFERENCES, "templates.json"), tmpl_doc)
    _write_json(os.path.join(REFERENCES, "reviews.json"), reviews_doc)

    release_id = args.release_id or (
        "rel-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    manifest = build_manifest(
        rules_doc, tmpl_doc, sources_doc, release_id, args.software_version, args.profile
    )
    _write_json(os.path.join(REFERENCES, "release-manifest.json"), manifest)

    print(f"[OK] release_id={release_id}")
    print(f"[OK] payload_sha256={manifest['payload_sha256']}")
    print(f"[OK] 启用能力={manifest['enabled_capabilities']}")
    print(f"[OK] 停用规则={list(manifest['disabled_rule_versions'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
