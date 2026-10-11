"""策略引擎（PolicyEngine）。

规格 4.1、4.3：
- 只计算显式建模的条件，不声称覆盖所有法律例外；
- 模型只给候选，程序决定本轮获准的能力与模板；
- 核心未知项需要追问，其他已明确的部分先帮助；
- 法律能力未启用时保留其他有依据的帮助。
"""

from __future__ import annotations

from .datamodels import TRUE, FALSE, UNKNOWN
from .predicates import evaluate, PredicateError
from .rules import RuleResolver, RuleResolutionError

# 输出顺序：先范围提示，再主线导航，然后草稿、来源定位，最后限制说明。
RULE_ORDER = [
    "RENT_SCOPE_CHECK",
    "RENT01_NAV",
    "RENT02_NAV",
    "RENT03_NAV",
    "RENT_DRAFT01",
    "RENT_SOURCE01",
    "RENT_LIMIT_NOTE",
    "RENT01_LEGAL",
    "RENT02_LEGAL",
    "RENT03_LEGAL",
]

QUESTION_KIND = "QUESTION"
MAX_QUESTIONS = 2


class PolicyEngine:
    def __init__(self, refs, resolver: RuleResolver, manifest: dict):
        self.refs = refs
        self.resolver = resolver
        self.enabled = set((manifest or {}).get("enabled_capabilities") or [])
        self.active_rule_versions = (manifest or {}).get("active_rule_versions") or {}

    # ---------------- 主入口 ----------------
    def plan(self, scenario_id: str, store, signals: dict) -> dict:
        traces: list[dict] = []
        capability_results: list[dict] = []
        selected: list[str] = []
        questions: list[str] = []
        reason_codes: list[str] = []
        seen: set[str] = set()
        template_rule_map: dict[str, list[dict]] = {}

        ordered = self._ordered_rules(scenario_id)
        for rule in ordered:
            rule_id = rule["rule_id"]
            caps = rule.get("capability_ids") or []
            if not caps:
                continue  # 纯依赖规则不直接产出可见内容
            try:
                trace = self.resolver.resolve(
                    rule_id, store, self.active_rule_versions.get(rule_id)
                )
            except RuleResolutionError as exc:
                trace = {
                    "rule_id": rule_id,
                    "decision": "ERROR",
                    "reason": str(exc),
                    "dependencies": [],
                    "blocked_templates": [],
                    "alternative_templates": [],
                    "unknown_templates": [],
                }
            traces.append(trace)

            for cap in caps:
                state = self._capability_state(cap, trace)
                capability_results.append({"id": cap, "state": state, "rule_id": rule_id})
                if state == "NOT_ENABLED" and rule.get("card_kind") == "LEGAL":
                    self._add(reason_codes, "PENDING_REVIEW")
                if trace["decision"] == "OUT_OF_SCOPE":
                    # 仅整体场景越界才记 OUT_OF_SCOPE；单条规则不适用不冒充越界
                    self._add(reason_codes, "OUT_OF_SCOPE")

            if trace["decision"] in ("ERROR",):
                self._add(reason_codes, "INTERNAL_ERROR")
                continue
            if trace["decision"] == "NEEDS_FACTS":
                self._add(reason_codes, "MISSING_FACT")

            candidates = self._candidate_templates(rule, trace)
            for tid in candidates:
                if tid in seen:
                    continue
                tmpl = self.refs.templates.get(tid)
                if tmpl is None:
                    self._add(reason_codes, "INTERNAL_ERROR")
                    continue
                if not self._template_gate(tmpl, store, trace):
                    continue
                if not self._capability_allowed(rule, tmpl):
                    continue
                rule_ref = {
                    "id": rule_id,
                    "version": rule.get("version"),
                    "sha256": rule.get("semantic_sha256"),
                    "hash_kind": "SEMANTIC",
                }
                if tid not in template_rule_map:
                    template_rule_map[tid] = []
                if rule_ref not in template_rule_map[tid]:
                    template_rule_map[tid].append(rule_ref)
                if tmpl.get("kind") == QUESTION_KIND:
                    if tid not in questions:
                        questions.append(tid)
                    continue
                seen.add(tid)
                selected.append(tid)

        questions = self._budget_questions(questions, store)

        if any(g for g in store.snapshot.conflict_groups):
            self._add(reason_codes, "FACT_CONFLICT")

        return {
            "traces": traces,
            "capability_results": capability_results,
            "selected_templates": selected,
            "question_templates": questions,
            "reason_codes": reason_codes,
            "template_rule_map": dict(template_rule_map),
            "rules_in_play": [t["rule_id"] for t in traces],
        }

    # ---------------- 内部 ----------------
    def _ordered_rules(self, scenario_id: str) -> list[dict]:
        rules = {r["rule_id"]: r for r in self.refs.rules_for_scenario(scenario_id)}
        out = [rules[r] for r in RULE_ORDER if r in rules]
        rest = [r for rid, r in sorted(rules.items()) if rid not in RULE_ORDER]
        return out + rest

    def _capability_state(self, cap: str, trace: dict) -> str:
        if cap not in self.enabled:
            return "NOT_ENABLED"
        decision = trace["decision"]
        mapping = {
            "ELIGIBLE": "DELIVERED",
            "NEEDS_FACTS": "NEEDS_FACTS",
            "NOT_ENABLED": "NOT_ENABLED",
            "OUT_OF_SCOPE": "OUT_OF_SCOPE",
            "PREMISE_UNMET": "NEEDS_FACTS",
            "NOT_APPLICABLE": "OUT_OF_SCOPE",
            "ERROR": "ERROR",
        }
        return mapping.get(decision, "ERROR")

    def _capability_allowed(self, rule: dict, tmpl: dict) -> bool:
        """法律类模板必须所属能力已启用；来源类模板要求来源可用。"""
        caps = rule.get("capability_ids") or []
        if tmpl.get("kind") == "LEGAL_EXPLANATION":
            if not ("LEGAL01" in caps or "LEGAL02" in caps):
                return False
            if not all(c in self.enabled for c in caps):
                return False
        for cap in caps:
            if cap and cap not in self.enabled and tmpl.get("kind") != "LIMITATION":
                return False
        return True

    def _candidate_templates(self, rule: dict, trace: dict) -> list[str]:
        blocked = set(trace.get("blocked_templates") or [])
        cands: list[str] = []
        decision = trace["decision"]
        if decision in ("ELIGIBLE", "NEEDS_FACTS"):
            cands.extend(rule.get("allowed_template_ids") or [])
        elif decision in ("PREMISE_UNMET", "OUT_OF_SCOPE", "NOT_APPLICABLE"):
            cands.extend(trace.get("alternative_templates") or [])
        cands.extend(trace.get("unknown_templates") or [])
        cands.extend(trace.get("alternative_templates") or [])
        out = []
        for tid in cands:
            if tid in blocked:
                continue
            if tid not in out:
                out.append(tid)
        return out

    def _template_gate(self, tmpl: dict, store, trace: dict) -> bool:
        pred = tmpl.get("required_predicates")
        if not pred:
            return True
        try:
            state = evaluate(pred, store)
        except PredicateError:
            return False
        return state == TRUE

    def _budget_questions(self, questions: list[str], store) -> list[str]:
        out: list[str] = []
        current_rev = store.snapshot.revision
        for tid in questions:
            if len(out) >= MAX_QUESTIONS:
                break
            if self._recently_asked(tid, store, current_rev):
                continue
            out.append(tid)
        return out

    def _recently_asked(self, tid: str, store, current_rev: int) -> bool:
        for entry in store.snapshot.asked_questions:
            if isinstance(entry, dict):
                if entry.get("template_id") == tid and current_rev - int(
                    entry.get("revision", -99)
                ) < 2:
                    return True
            elif entry == tid:
                return True
        return False

    @staticmethod
    def _add(codes: list[str], code: str) -> None:
        if code not in codes:
            codes.append(code)
