"""参考数据加载与摘要校验。

规格 5、10.1：
- 引用一律带 id、version、sha256、hash_kind，禁止仅凭 ID 自动换用最新版本；
- 加载时校验语义摘要，摘要不符即拒绝该条规则或模板；
- 包内路径相对模块位置解析，不依赖开发者当前目录。
"""

from __future__ import annotations

import json
import os
from typing import Any

from . import hashing

# __file__ = <包根>/scripts/core/loader.py，上溯三级得到包根。
# 路径相对模块位置解析，不依赖调用者当前目录。
PACKAGE_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
REFERENCES_DIR = os.path.join(PACKAGE_ROOT, "references")


class IntegrityError(ValueError):
    pass


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class ReferenceSet:
    def __init__(self, references_dir: str = REFERENCES_DIR):
        self.dir = references_dir
        rules_doc = _read_json(os.path.join(references_dir, "rules.json"))
        tmpl_doc = _read_json(os.path.join(references_dir, "templates.json"))
        self.rules: dict[str, dict] = {}
        self.templates: dict[str, dict] = {}
        self.integrity_errors: list[str] = []

        for rule in rules_doc.get("rules", []):
            expected = hashing.rule_semantic_sha256(rule)
            stored = rule.get("semantic_sha256") or ""
            if stored and stored != expected:
                self.integrity_errors.append(
                    f"规则 {rule['rule_id']} 语义摘要不符（期望 {expected[:12]}，实际 {stored[:12]}）"
                )
                continue
            self.rules[rule["rule_id"]] = rule

        for tmpl in tmpl_doc.get("templates", []):
            expected = hashing.template_semantic_sha256(tmpl)
            stored = tmpl.get("semantic_sha256") or ""
            if stored and stored != expected:
                self.integrity_errors.append(
                    f"模板 {tmpl['template_id']} 语义摘要不符（期望 {expected[:12]}，实际 {stored[:12]}）"
                )
                continue
            self.templates[tmpl["template_id"]] = tmpl

        self.sources: dict[str, dict] = {}
        src_path = os.path.join(references_dir, "sources.json")
        if os.path.exists(src_path):
            for rec in _read_json(src_path).get("sources", []):
                self.sources[rec["source_id"]] = rec

        self.reviews: list[dict] = []
        rev_path = os.path.join(references_dir, "reviews.json")
        if os.path.exists(rev_path):
            self.reviews = _read_json(rev_path).get("reviews", [])

        self.manifest: dict = {}
        man_path = os.path.join(references_dir, "release-manifest.json")
        if os.path.exists(man_path):
            self.manifest = _read_json(man_path)

    # ---- 来源 ----
    def source_article(self, source_id: str, version: str, provision_locator: str) -> dict:
        rec = self.sources.get(source_id)
        if rec is None:
            raise IntegrityError(f"未登记来源：{source_id}")
        if rec.get("version") != version:
            raise IntegrityError(
                f"来源版本不符：{source_id} 需要 {version}，实际 {rec.get('version')}"
            )
        for art in rec.get("articles", []):
            if art.get("provision_locator") == provision_locator:
                return art
        raise IntegrityError(f"来源 {source_id} 无定位 {provision_locator}")

    def source_available(self, source_id: str, version: str) -> bool:
        rec = self.sources.get(source_id)
        if rec is None or rec.get("version") != version:
            return False
        return rec.get("retrieval_state") == "AVAILABLE"

    def template(self, template_id: str, version: str | None = None) -> dict:
        rec = self.templates.get(template_id)
        if rec is None:
            raise IntegrityError(f"未登记模板：{template_id}")
        if version and rec.get("version") != version:
            raise IntegrityError(
                f"模板版本不符：{template_id} 需要 {version}，实际 {rec.get('version')}"
            )
        return rec

    def rule(self, rule_id: str) -> dict:
        rec = self.rules.get(rule_id)
        if rec is None:
            raise IntegrityError(f"未登记规则：{rule_id}")
        return rec

    def rules_for_scenario(self, scenario_id: str) -> list[dict]:
        return [r for r in self.rules.values() if r.get("scenario_id") == scenario_id]
