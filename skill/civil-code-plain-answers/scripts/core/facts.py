"""会话事实存储（SessionStore）。

规格 5.4、4.3：
- 事实必须绑定原话与可重建的 span（零起点 Unicode 码点半开区间）；
- 用户陈述不等于事实已被证明，程序不产生 PROVEN 等状态；
- 明确纠正才 supersedes；只是另一方说法不同则保留 CONFLICT；
- 会话之间隔离。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .datamodels import (
    ASSERTED,
    CONFLICT,
    FactRecord,
    RETRACTED,
    SessionSnapshot,
    UNKNOWN_STATE,
)

# 事实键 -> 取值类型。未知键一律拒绝，避免模型引入任意字段。
FACT_SCHEMA: dict[str, str] = {
    "occupancy_still_living": "bool",
    "occupancy_moved_out": "bool",
    "keys_returned": "bool",
    "handover_record_signed": "bool",
    "deposit_clause_return_time": "text",
    "deposit_clause_deduction": "text",
    "landlord_reason": "text",
    "claimed_amount": "money",
    "deduction_items": "text",
    "move_in_evidence": "bool",
    "move_out_evidence": "bool",
    "trace_preexisting": "bool",
    "landlord_dispute_handover": "bool",
    "early_termination": "bool",
    "sublet": "bool",
    "commercial_use": "bool",
    "damage_due_to_miskeeping": "bool",
    "jurisdiction": "enum",
    "contract_text_available": "bool",
    "image_attachment": "bool",
}

ENUM_VALUES = {
    "jurisdiction": {"CN_MAINLAND", "NON_MAINLAND", "UNKNOWN"},
}


class FactUpdateError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _coerce(key: str, value: Any) -> Any:
    if key not in FACT_SCHEMA:
        raise FactUpdateError(f"未登记的事实键：{key}")
    kind = FACT_SCHEMA[key]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ("true", "是", "yes", "1"):
                return True
            if low in ("false", "否", "no", "0"):
                return False
        raise FactUpdateError(f"{key} 需要布尔值：{value!r}")
    if kind == "money":
        # 金额用十进制字符串，不用二进制浮点
        if isinstance(value, (int,)) and not isinstance(value, bool):
            return str(value)
        if isinstance(value, str):
            cleaned = value.strip().replace(",", "").replace("元", "")
            if cleaned and all(ch in "0123456789." for ch in cleaned):
                return cleaned
        raise FactUpdateError(f"{key} 需要十进制字符串金额：{value!r}")
    if kind == "enum":
        allowed = ENUM_VALUES.get(key, set())
        if value not in allowed:
            raise FactUpdateError(f"{key} 取值 {value!r} 不在枚举 {sorted(allowed)}")
        return value
    if not isinstance(value, str):
        raise FactUpdateError(f"{key} 需要文本：{value!r}")
    return value


def _locate_span(message: str, quote: str) -> dict | None:
    """零起点 Unicode 码点半开区间；必须能从原消息重建 quote。"""
    if not quote:
        return None
    start = message.find(quote)
    if start < 0:
        return None
    end = start + len(quote)
    if message[start:end] != quote:
        return None
    return {"start": start, "end": end, "unit": "unicode_codepoint"}


class SessionStore:
    def __init__(self, snapshot: SessionSnapshot | None = None, session_id: str = ""):
        self.snapshot = snapshot or SessionSnapshot(
            session_id=session_id or str(uuid.uuid4())
        )
        self.changes: list[dict] = []

    # ---- 应用候选事实 ----
    def apply_updates(
        self,
        updates: list[dict],
        message: str,
        turn_id: str,
        speaker: str = "user",
        evidence_level: str = "USER_STATEMENT",
    ) -> list[dict]:
        applied: list[dict] = []
        for upd in updates or []:
            try:
                rec = self._apply_one(upd, message, turn_id, speaker, evidence_level)
            except FactUpdateError as exc:
                self.changes.append(
                    {"key": upd.get("key"), "result": "REJECTED", "reason": str(exc)}
                )
                continue
            if rec:
                applied.append(rec)
        return applied

    def _apply_one(
        self, upd: dict, message: str, turn_id: str, speaker: str, evidence_level: str
    ) -> dict | None:
        key = upd.get("key")
        if not isinstance(key, str):
            raise FactUpdateError("缺少 key")
        state = upd.get("state", ASSERTED)
        quote = upd.get("source_quote") or ""
        span = upd.get("source_span")
        computed = _locate_span(message, quote) if quote else None

        if quote and computed is None:
            # 模型给的原话在消息里找不到 -> 该候选不可用，不写入
            raise FactUpdateError(f"原话无法在原消息中定位：{quote[:30]!r}")
        if span is not None and computed is not None:
            if (
                not isinstance(span, dict)
                or span.get("start") != computed["start"]
                or span.get("end") != computed["end"]
            ):
                # 以程序计算为准，不采信模型自报偏移
                span = computed
        if quote:
            span = computed

        if state == UNKNOWN_STATE:
            rec = FactRecord(
                fact_id=str(uuid.uuid4()),
                key=key,
                value=None,
                state=UNKNOWN_STATE,
                speaker=speaker,
                evidence_level=evidence_level,
                turn_id=turn_id,
                source_quote=quote,
                source_span=span,
                created_at=_now(),
            )
            self._write(key, rec, upd)
            return {"key": key, "result": "UNKNOWN", "fact_id": rec.fact_id}

        if state == CONFLICT:
            old = self.snapshot.facts.get(key)
            rec = FactRecord(
                fact_id=str(uuid.uuid4()),
                key=key,
                value=None,
                state=CONFLICT,
                speaker=speaker,
                evidence_level=evidence_level,
                turn_id=turn_id,
                source_quote=quote,
                source_span=span,
                supersedes=[old.fact_id] if old else [],
                created_at=_now(),
            )
            self.snapshot.facts[key] = rec
            self.snapshot.conflict_groups.append(
                {
                    "key": key,
                    "fact_id": rec.fact_id,
                    "turn_id": turn_id,
                    "quote": quote,
                    "superseded_fact_id": old.fact_id if old else None,
                }
            )
            self.changes.append({"key": key, "result": "CONFLICT", "fact_id": rec.fact_id})
            return {"key": key, "result": "CONFLICT", "fact_id": rec.fact_id}

        value = _coerce(key, upd.get("value"))
        old = self.snapshot.facts.get(key)
        rec = FactRecord(
            fact_id=str(uuid.uuid4()),
            key=key,
            value=value,
            state=ASSERTED,
            speaker=speaker,
            evidence_level=evidence_level,
            turn_id=turn_id,
            source_quote=quote,
            source_span=span,
            created_at=_now(),
        )
        self._write(key, rec, upd, old)
        return {"key": key, "result": "ASSERTED", "fact_id": rec.fact_id}

    def _write(self, key: str, rec: FactRecord, upd: dict, old=None) -> None:
        old = old if old is not None else self.snapshot.facts.get(key)
        is_correction = bool(upd.get("is_correction")) or bool(upd.get("supersedes"))
        if old is not None and old.state == CONFLICT and not is_correction:
            # 冲突未解决前，不按「最新一句话」覆盖
            self.changes.append(
                {"key": key, "result": "HELD_CONFLICT", "fact_id": rec.fact_id}
            )
            return
        if old is not None and is_correction:
            rec.supersedes = [old.fact_id]
            old.state = RETRACTED
            self.snapshot.invalidated_advice.append(
                f"{key}@{old.fact_id}"
            )
        self.snapshot.facts[key] = rec
        self.changes.append(
            {
                "key": key,
                "result": rec.state,
                "fact_id": rec.fact_id,
                "supersedes": rec.supersedes,
            }
        )

    def bump(self) -> None:
        self.snapshot.revision += 1
        self.snapshot.updated_at = _now()

    def diff(self, before_revision: int) -> dict:
        return {
            "from_revision": before_revision,
            "to_revision": self.snapshot.revision,
            "changes": list(self.changes),
        }
