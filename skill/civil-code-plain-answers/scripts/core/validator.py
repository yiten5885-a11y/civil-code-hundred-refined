"""最终校验（FinalValidator）。

规格 4.4、5.3、11.2-G05：
- 显式条件与结构检查；不承担通用语义裁判；
- 法律句、事实和填充值都要有绑定；
- 未支持结论与编造数字一律拦下；
- 依据、审核或条件不足的直接收窄，并保留失败状态。
"""

from __future__ import annotations

import re

from . import hashing
from .datamodels import SEMANTIC

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
MAX_QUESTIONS = 2


class FinalValidator:
    def __init__(self, refs):
        self.refs = refs

    def validate(self, blocks: list[dict], questions: list[str], citations: list[dict],
                 rules_in_play: list[str], plan_traces: list[dict]) -> dict:
        checks: list[dict] = []
        removed: list[dict] = []
        kept: list[dict] = []

        def rec(check_id: str, ok: bool, detail: str = "") -> None:
            checks.append({"check": check_id, "status": "PASS" if ok else "FAIL", "detail": detail})

        # V1 法律解释必须来自已启用且已复核的规则与模板
        for b in blocks:
            if b["kind"] != "LEGAL_EXPLANATION":
                kept.append(b)
                continue
            tmpl = self.refs.templates.get(b["template_id"])
            rule_ok = False
            for rid in b.get("rule_refs") or []:
                rule = self.refs.rules.get(rid.get("id") if isinstance(rid, dict) else rid)
                if rule and rule.get("lifecycle_state") == "ACTIVE" and rule.get("review_refs"):
                    rule_ok = True
            tmpl_ok = bool(tmpl and tmpl.get("review_refs"))
            if rule_ok and tmpl_ok:
                kept.append(b)
                rec("V1_LEGAL_REVIEW_BOUND", True, b["template_id"])
            else:
                removed.append({"template_id": b["template_id"], "reason": "法律表达缺少真实复核绑定"})
                rec("V1_LEGAL_REVIEW_BOUND", False, b["template_id"])

        # V2 数字必须来自模板原文或已绑定的槽位
        for b in kept:
            tmpl = self.refs.templates.get(b["template_id"])
            if tmpl is None:
                removed.append({"template_id": b["template_id"], "reason": "模板未登记"})
                continue
            allowed = set(NUMBER_RE.findall(tmpl["text"]))
            for bind in (b.get("slot_bindings") or {}).values():
                allowed |= set(NUMBER_RE.findall(str(bind.get("value", ""))))
            present = set(NUMBER_RE.findall(b["text"]))
            stray = present - allowed
            if stray:
                removed.append(
                    {"template_id": b["template_id"], "reason": f"出现未绑定数字 {sorted(stray)}"}
                )
                rec("V2_NUMBERS_BOUND", False, f"{b['template_id']}: {sorted(stray)}")
            else:
                rec("V2_NUMBERS_BOUND", True, b["template_id"])

        kept = [b for b in kept if not any(
            r.get("template_id") == b["template_id"] and "未绑定数字" in r.get("reason", "")
            for r in removed
        )]

        # V3 引用必须来自可用且已核验的来源
        bad_citations = [
            c for c in citations
            if c.get("retrieval_state") != "AVAILABLE"
            or c.get("verification_state") not in ("VERIFIED", "CONFLICT")
        ]
        rec("V3_CITATION_SOURCE_OK", not bad_citations, str([c.get("source_id") for c in bad_citations]))
        if bad_citations:
            kept = [
                b for b in kept
                if not any(
                    s.get("source_id") in {c.get("source_id") for c in bad_citations}
                    for s in (b.get("source_refs") or [])
                )
            ]

        # V4 禁推结论的词面扫描（结构性检查，不声称拦截所有同义句）
        prohibited: list[str] = []
        for rid in rules_in_play:
            rule = self.refs.rules.get(rid)
            if rule:
                prohibited.extend(rule.get("prohibited_inferences") or [])
        full_text = "\n".join(b["text"] for b in kept)
        hits = [p for p in prohibited if p and p in full_text]
        rec("V4_PROHIBITED_SCAN", not hits, str(hits))

        # V5 追问数量
        q_ok = len(questions) <= MAX_QUESTIONS
        rec("V5_QUESTION_BUDGET", q_ok, f"{len(questions)} 项")

        # V6 事实类块必须有绑定
        factless = [
            b["template_id"] for b in kept
            if b["kind"] == "FACT_SUMMARY" and not (b.get("slot_bindings") or {})
        ]
        rec("V6_FACT_SUMMARY_BOUND", not factless, str(factless))

        # V7 文本非空
        rec("V7_TEXT_NOT_EMPTY", bool(full_text.strip()))

        status = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
        return {
            "status": status,
            "checks": checks,
            "blocks": kept,
            "removed": removed,
            "citation_count": len(citations),
        }

    @staticmethod
    def text_sha256(text: str) -> str:
        return hashing.sha256_text(text)
