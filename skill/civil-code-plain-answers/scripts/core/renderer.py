"""渲染器（Renderer）。

规格 4.1、4.3.10、5.3：
- 负责全部可见内容，包括引用、追问和固定提示；
- 不调用模型重新自由改写法律句子；
- 缺项在草稿中显示「待填写」，不自动补成具体数额或日期；
- 金额用十进制字符串，不采用二进制浮点数。
"""

from __future__ import annotations

from . import hashing
from .datamodels import ASSERTED, CONFLICT
from .loader import IntegrityError

FACT_LABELS = {
    "occupancy_still_living": "是否仍居住",
    "occupancy_moved_out": "是否已搬离",
    "keys_returned": "钥匙是否交回",
    "handover_record_signed": "是否有交接记录",
    "deposit_clause_return_time": "押金退还时间约定",
    "deposit_clause_deduction": "押金扣减情形约定",
    "landlord_reason": "房东的理由",
    "claimed_amount": "对方主张的金额",
    "deduction_items": "扣款项目",
    "move_in_evidence": "入住时材料",
    "move_out_evidence": "退房时材料",
    "trace_preexisting": "痕迹入住时是否已存在",
    "landlord_dispute_handover": "双方对交接的说法",
    "early_termination": "是否提前退租",
    "sublet": "是否转租",
    "commercial_use": "是否非住宅用途",
    "damage_due_to_miskeeping": "是否保管不善",
    "jurisdiction": "适用地域",
    "contract_text_available": "是否有合同原文",
    "image_attachment": "是否附带图片",
}

BLOCK_ORDER = [
    "SAFETY",
    "FACT_SUMMARY",
    "ACTION",
    "SOURCE_LOCATOR",
    "LEGAL_EXPLANATION",
    "DRAFT",
    "QUESTION",
    "LIMITATION",
]


class RenderError(ValueError):
    pass


class Renderer:
    def __init__(self, refs):
        self.refs = refs

    # ---------------- 主入口 ----------------
    def render(self, template_ids: list[str], store, signals: dict) -> dict:
        blocks: list[dict] = []
        citations: list[dict] = []
        skipped: list[dict] = []

        for tid in template_ids:
            tmpl = self.refs.templates.get(tid)
            if tmpl is None:
                skipped.append({"template_id": tid, "reason": "未登记模板"})
                continue
            try:
                text, bound = self._render_one(tmpl, store, signals)
            except (RenderError, IntegrityError) as exc:
                # 来源缺失或摘要不符时跳过该块，不凭记忆补法条
                skipped.append({"template_id": tid, "reason": str(exc)})
                continue
            block = {
                "kind": tmpl["kind"],
                "template_id": tmpl["template_id"],
                "template_version": tmpl["version"],
                "text": text,
                "fact_refs": bound.get("fact_refs", []),
                "rule_refs": bound.get("rule_refs", []),
                "source_refs": bound.get("source_refs", []),
                "slot_bindings": bound.get("slots", {}),
            }
            blocks.append(block)
            for src in bound.get("source_refs", []):
                if src not in citations:
                    citations.append(src)

        blocks.sort(key=lambda b: BLOCK_ORDER.index(b["kind"]) if b["kind"] in BLOCK_ORDER else 99)
        text = self._assemble(blocks)
        return {
            "blocks": blocks,
            "text": text,
            "citations": citations,
            "skipped": skipped,
        }

    # ---------------- 槽位绑定 ----------------
    def _render_one(self, tmpl: dict, store, signals: dict) -> tuple[str, dict]:
        bound: dict = {"slots": {}, "fact_refs": [], "source_refs": [], "rule_refs": []}
        text = tmpl["text"]
        for name, spec in (tmpl.get("slots") or {}).items():
            value, meta = self._bind(name, spec, tmpl, store, signals)
            if value is None:
                if spec.get("required") and tmpl["kind"] == "DRAFT":
                    value = "待填写"
                elif spec.get("required"):
                    raise RenderError(f"模板 {tmpl['template_id']} 缺少必填槽位 {name}")
                else:
                    value = ""
            bound["slots"][name] = {"value": value, **meta}
            if meta.get("fact_id"):
                bound["fact_refs"].append(meta["fact_id"])
            if meta.get("citation"):
                bound["source_refs"].append(meta["citation"])
            text = text.replace("{" + name + "}", str(value))
        return text, bound

    def _bind(self, name: str, spec: dict, tmpl: dict, store, signals: dict):
        kind = spec.get("source_kind")
        if kind == "fact":
            rec = store.snapshot.facts.get(spec.get("fact_key"))
            if rec is None or rec.state in (CONFLICT,):
                return None, {"kind": "fact", "missing": True}
            value = rec.value
            if spec.get("type") == "money" and value is not None:
                value = str(value)
            return value, {
                "kind": "fact",
                "fact_key": rec.key,
                "fact_id": rec.fact_id,
                "state": rec.state,
                "evidence_level": rec.evidence_level,
                "quote": rec.source_quote,
            }
        if kind == "derived":
            fn = getattr(self, "_derive_" + spec.get("derivation", ""), None)
            if fn is None:
                raise RenderError(f"未登记的派生：{spec.get('derivation')}")
            return fn(store)
        if kind == "signal":
            return signals.get(spec.get("signal_key")), {"kind": "signal"}
        if kind == "source_article":
            srefs = tmpl.get("source_refs") or []
            if not srefs:
                raise RenderError(f"模板 {tmpl['template_id']} 缺少 source_refs")
            sref = srefs[0]
            art = self.refs.source_article(
                sref["id"], sref["version"], spec.get("provision_locator")
            )
            if not self.refs.source_available(sref["id"], sref["version"]):
                raise RenderError(f"来源不可用：{sref['id']}@{sref['version']}")
            # 先证明正文与它自己登记的摘要一致（防止正文被替换后仍被引用）
            recorded_text_sha = art.get("canonical_sha256")
            actual_text_sha = hashing.sha256_text(art.get("canonical_text") or "")
            if recorded_text_sha and actual_text_sha != recorded_text_sha:
                raise IntegrityError(
                    f"来源正文摘要不符：{sref['id']} {spec.get('provision_locator')}"
                )
            # 再核对模板绑定的来源版本摘要
            expected_sha = sref.get("sha256")
            if expected_sha and recorded_text_sha and expected_sha != recorded_text_sha:
                raise RenderError(
                    f"来源摘要不符：{sref['id']} {spec.get('provision_locator')}"
                )
            citation = self._citation(sref, art)
            return art["canonical_text"], {"kind": "source", "citation": citation}
        if kind == "source_field":
            srefs = tmpl.get("source_refs") or []
            if not srefs:
                raise RenderError(f"模板 {tmpl['template_id']} 缺少 source_refs")
            sref = srefs[0]
            rec = self.refs.sources.get(sref["id"])
            if rec is None:
                raise RenderError(f"未登记来源：{sref['id']}")
            if not self.refs.source_available(sref["id"], sref["version"]):
                raise RenderError(f"来源不可用：{sref['id']}@{sref['version']}")
            return rec.get(spec.get("field")), {"kind": "source_field"}
        raise RenderError(f"未登记的槽位来源：{kind}")

    def _citation(self, sref: dict, art: dict) -> dict:
        rec = self.refs.sources[sref["id"]]
        return {
            "source_id": rec["source_id"],
            "version": rec["version"],
            "title": rec.get("title"),
            "issuer": rec.get("issuer"),
            "provision_locator": art.get("provision_locator"),
            "official_url": rec.get("official_url"),
            "canonical_sha256": art.get("canonical_sha256"),
            "hash_kind": "CANONICAL_TEXT",
            "raw_sha256": rec.get("raw_sha256"),
            "verified_at": rec.get("verified_at"),
            "verification_state": rec.get("verification_state"),
            "retrieval_state": rec.get("retrieval_state"),
            "effect_state": rec.get("effect_state"),
        }

    # ---------------- 派生 ----------------
    def _derive_occupancy_summary(self, store):
        parts: list[str] = []
        facts = store.snapshot.facts

        def val(key):
            rec = facts.get(key)
            if rec is None or rec.state == CONFLICT:
                return None
            return rec.value

        still = val("occupancy_still_living")
        moved = val("occupancy_moved_out")
        keys = val("keys_returned")
        handover = val("handover_record_signed")
        if still is True:
            parts.append("你目前还住着")
        elif still is False:
            parts.append("你已经不住在那里")
        if moved is True:
            parts.append("已经搬走")
        if keys is True:
            parts.append("钥匙已交回")
        elif keys is False:
            parts.append("钥匙还没交")
        if handover is True:
            parts.append("有交接记录")
        elif handover is False:
            parts.append("没有交接记录")
        if not parts:
            return None, {"kind": "derived", "missing": True}
        return "、".join(parts), {"kind": "derived", "derivation": "occupancy_summary"}

    def _derive_conflict_summary(self, store):
        groups = [g for g in store.snapshot.conflict_groups]
        if not groups:
            return None, {"kind": "derived", "missing": True}
        labels = []
        for g in groups:
            labels.append(FACT_LABELS.get(g.get("key"), g.get("key")))
        uniq = sorted(set(labels))
        return "、".join(f"关于「{x}」，两边的说法不一致" for x in uniq), {
            "kind": "derived",
            "derivation": "conflict_summary",
        }

    # ---------------- 组装 ----------------
    def _assemble(self, blocks: list[dict]) -> str:
        if not blocks:
            return ""
        groups: list[str] = []
        buf: list[str] = []
        buf_kind = None
        for b in blocks:
            kind = b["kind"]
            if kind in ("DRAFT", "SAFETY"):
                if buf:
                    groups.append("\n".join(buf))
                    buf = []
                groups.append(b["text"])
                buf_kind = None
                continue
            if buf_kind is not None and buf_kind != kind:
                groups.append("\n".join(buf))
                buf = []
            buf.append(b["text"])
            buf_kind = kind
        if buf:
            groups.append("\n".join(buf))
        return "\n\n".join(g for g in groups if g.strip())

    @staticmethod
    def text_sha256(text: str) -> str:
        return hashing.sha256_text(text)
