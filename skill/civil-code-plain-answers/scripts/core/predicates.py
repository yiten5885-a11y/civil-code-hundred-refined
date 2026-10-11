"""三值条件求值。

规格 5.2：
- 只支持白名单操作符，不保存或执行任意代码；
- exists 仅表示有可用陈述记录，不表示该陈述为真，也不表示事实已证明；
- 事实缺失或冲突返回 UNKNOWN；NOT UNKNOWN 仍为 UNKNOWN；
- all 中存在 FALSE 则 FALSE，否则存在 UNKNOWN 则 UNKNOWN；
- any 中存在 TRUE 则 TRUE，否则存在 UNKNOWN 则 UNKNOWN；
- 不得用「字段为空」推导为「没有协议」「没有损坏」。
"""

from __future__ import annotations

from typing import Any

from .datamodels import TRUE, FALSE, UNKNOWN, CONFLICT, RETRACTED

ALLOWED_OPS = {"exists", "equals", "one_of", "all", "any", "not"}

# 谓词可以引用事实（fact）或本轮派生的会话信号（signal）。
# signal 由输入分析程序计算，不是用户陈述，也不代表事实已被证明。
ALLOWED_SIGNALS = {
    "safety_now",
    "safety_history",
    "asks_legal_conclusion",
    "asks_wear_conclusion",
    "asks_clause_validity",
    "asks_draft",
    "asks_source",
    "input_oversize",
}


class PredicateError(ValueError):
    pass


def _check(pred: Any) -> dict:
    if not isinstance(pred, dict):
        raise PredicateError(f"谓词必须是对象：{pred!r}")
    op = pred.get("op")
    if op not in ALLOWED_OPS:
        raise PredicateError(f"不支持的操作符：{op!r}（白名单：{sorted(ALLOWED_OPS)}）")
    return pred


def evaluate(pred: Any, store: "FactStore") -> str:  # noqa: F821
    pred = _check(pred)
    op = pred["op"]
    if op == "exists":
        key = pred["fact"]
        return TRUE if store.has_record(key) else FALSE
    if op in ("equals", "one_of"):
        if pred.get("signal") is not None:
            name = pred["signal"]
            if name not in ALLOWED_SIGNALS:
                raise PredicateError(f"未登记的信号：{name}")
            actual = (TRUE, store.signal(name))
            if op == "equals":
                return _cmp(actual, pred.get("value"), eq=True)
            return _any([_cmp(actual, v, eq=True) for v in pred.get("values") or []])
        if op == "equals":
            return _cmp(store.get(pred["fact"]), pred.get("value"), eq=True)
        values = pred.get("values") or []
        if len(values) == 1:
            return _cmp(store.get(pred["fact"]), values[0], eq=True)
        results = [_cmp(store.get(pred["fact"]), v, eq=True) for v in values]
        return _any(results)
    if op == "all":
        return _all([evaluate(p, store) for p in pred.get("of") or []])
    if op == "any":
        return _any([evaluate(p, store) for p in pred.get("of") or []])
    if op == "not":
        inner = evaluate(pred["of"], store)
        return UNKNOWN if inner == UNKNOWN else (FALSE if inner == TRUE else TRUE)
    raise PredicateError(op)  # pragma: no cover


def _cmp(actual: Any, expected: Any, eq: bool) -> str:
    """actual 为 (state, value) 元组。"""
    state, value = actual
    if state in (UNKNOWN, CONFLICT, RETRACTED) or value is None:
        return UNKNOWN
    same = value == expected
    return TRUE if (same == eq) else FALSE


def _all(results: list[str]) -> str:
    if any(r == FALSE for r in results):
        return FALSE
    if any(r == UNKNOWN for r in results):
        return UNKNOWN
    return TRUE


def _any(results: list[str]) -> str:
    if any(r == TRUE for r in results):
        return TRUE
    if any(r == UNKNOWN for r in results):
        return UNKNOWN
    return FALSE


class FactStore:
    """会话事实访问层。不判断证据真伪，只做状态管理。"""

    def __init__(self, snapshot, signals: dict | None = None):
        self.snapshot = snapshot
        self.signals = dict(signals or {})

    def signal(self, name: str) -> bool:
        return bool(self.signals.get(name, False))

    def has_record(self, key: str) -> bool:
        rec = self.snapshot.facts.get(key)
        return rec is not None and rec.state != RETRACTED

    def get(self, key: str) -> tuple[str, Any]:
        """返回 (state, value)。缺失一律返回 UNKNOWN，不推导为「没有」。"""
        rec = self.snapshot.facts.get(key)
        if rec is None or rec.state == RETRACTED:
            return UNKNOWN, None
        if rec.state == CONFLICT:
            return CONFLICT, None
        return rec.state, rec.value

    def is_missing(self, key: str) -> bool:
        """没有可用陈述，或明确未知/冲突 —— 都需要追问或保留不确定。"""
        state, _ = self.get(key)
        return state in (UNKNOWN, CONFLICT)
