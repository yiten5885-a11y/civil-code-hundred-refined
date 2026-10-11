"""规则解析与依赖展开（RuleResolver）。

规格 4.3.5、5.2：
- 主规则和登记过的例外一起进入判断，不靠相似检索碰运气；
- PREMISE 依赖必须满足；
- EXCEPTION 为 TRUE 时停用 block_template_ids，只转用已登记且获准的例外表达；
  为 UNKNOWN 或冲突时，只用指定的条件式表达、追问或导航；
  为 FALSE 时按一般规则自身条件继续；
- COMPANION 不具阻断作用；
- 缺少必要依赖、版本不符或依赖循环 -> 该法律输出不可用。
"""

from __future__ import annotations

from typing import Any

from .datamodels import TRUE, FALSE, UNKNOWN, SEMANTIC
from .predicates import evaluate, PredicateError

RELATIONS = {"PREMISE", "EXCEPTION", "COMPANION"}


class RuleResolutionError(ValueError):
    pass


class RuleResolver:
    def __init__(self, rules: dict[str, dict], templates: dict[str, dict]):
        self.rules = rules
        self.templates = templates

    def by_id_version(self, rule_id: str, version: str | None = None) -> dict:
        rec = self.rules.get(rule_id)
        if rec is None:
            raise RuleResolutionError(f"未登记的规则：{rule_id}")
        if version and rec.get("version") != version:
            raise RuleResolutionError(
                f"规则版本不符：{rule_id} 需要 {version}，实际 {rec.get('version')}"
            )
        return rec

    def resolve(
        self, rule_id: str, store, version: str | None = None, _seen: tuple = ()
    ) -> dict:
        """返回该规则的判断结果与依赖轨迹。"""
        if rule_id in _seen:
            raise RuleResolutionError(f"依赖循环：{' -> '.join(_seen + (rule_id,))}")
        rule = self.by_id_version(rule_id, version)
        trace: dict[str, Any] = {
            "rule_id": rule_id,
            "version": rule.get("version"),
            "card_kind": rule.get("card_kind"),
            "lifecycle_state": rule.get("lifecycle_state"),
            "dependencies": [],
            "blocked_templates": [],
            "alternative_templates": [],
            "unknown_templates": [],
        }

        # 1. 生命周期
        if rule.get("lifecycle_state") != "ACTIVE":
            trace["decision"] = "NOT_ENABLED"
            trace["reason"] = f"lifecycle_state={rule.get('lifecycle_state')}"
            return trace

        # 2. 范围谓词
        scope = rule.get("scope_predicates")
        scope_state = TRUE
        if scope:
            try:
                scope_state = evaluate(scope, store)
            except PredicateError as exc:
                trace["decision"] = "ERROR"
                trace["reason"] = f"谓词错误：{exc}"
                return trace
        trace["scope_state"] = scope_state
        if scope_state == FALSE:
            trace["decision"] = "OUT_OF_SCOPE"
            trace["reason"] = "scope_predicates 为 FALSE"
            return trace

        # 3. 依赖展开
        premise_unmet = False
        for dep in rule.get("dependencies") or []:
            dep_id = dep.get("rule_ref", {}).get("id")
            dep_version = dep.get("rule_ref", {}).get("version")
            relation = dep.get("relation")
            required = bool(dep.get("required", True))
            if relation not in RELATIONS:
                raise RuleResolutionError(f"未登记的依赖关系：{relation}")
            dep_rule = self.by_id_version(dep_id, dep_version)

            # 例外/前提规则的判定条件来自其自身 predicates
            dep_pred = dep_rule.get("predicates")
            dep_state = TRUE
            if dep_pred:
                try:
                    dep_state = evaluate(dep_pred, store)
                except PredicateError as exc:
                    dep_state = UNKNOWN
                    trace["dependencies"].append(
                        {"id": dep_id, "relation": relation, "state": "ERROR", "error": str(exc)}
                    )
                    if required and relation == "PREMISE":
                        premise_unmet = True
                    continue
            entry = {
                "id": dep_id,
                "version": dep_rule.get("version"),
                "relation": relation,
                "state": dep_state,
                "required": required,
            }
            trace["dependencies"].append(entry)

            if relation == "EXCEPTION":
                if dep_state == TRUE:
                    trace["blocked_templates"].extend(dep.get("block_template_ids") or [])
                    trace["alternative_templates"].extend(
                        dep.get("alternative_template_refs") or []
                    )
                elif dep_state == UNKNOWN:
                    trace["blocked_templates"].extend(dep.get("block_template_ids") or [])
                    trace["unknown_templates"].extend(dep.get("unknown_template_refs") or [])
            elif relation == "PREMISE":
                if dep_state == FALSE and required:
                    premise_unmet = True
                if dep_state == UNKNOWN and required:
                    premise_unmet = True

        if premise_unmet:
            trace["decision"] = "PREMISE_UNMET"
            trace["reason"] = "必要前提未满足或未知"
            # 前提不满足时转用依赖规则登记的替代表达
            for dep in rule.get("dependencies") or []:
                if dep.get("relation") == "PREMISE":
                    trace["alternative_templates"].extend(
                        dep.get("alternative_template_refs") or []
                    )
            return trace

        # 4. 规则自身 predicates
        own = rule.get("predicates")
        own_state = TRUE
        if own:
            try:
                own_state = evaluate(own, store)
            except PredicateError as exc:
                trace["decision"] = "ERROR"
                trace["reason"] = f"谓词错误：{exc}"
                return trace
        trace["predicate_state"] = own_state

        if scope_state == UNKNOWN or own_state == UNKNOWN:
            trace["decision"] = "NEEDS_FACTS"
            trace["reason"] = "关键条件未知"
            return trace
        if own_state == FALSE:
            trace["decision"] = "NOT_APPLICABLE"
            trace["reason"] = "自身条件为 FALSE"
            return trace

        trace["decision"] = "ELIGIBLE"
        return trace

    def template_ids(self, rule: dict) -> list[str]:
        return list(rule.get("allowed_template_ids") or [])
