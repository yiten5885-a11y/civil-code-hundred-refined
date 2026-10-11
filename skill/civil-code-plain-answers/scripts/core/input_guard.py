"""输入检查与安全分流（InputGuard / 安全流程）。

规格 9.3、9.4：
- 人身安全分流先执行，不等待法律来源检索或财产问卷；
- 不能把历史描述、讨论法条、引述案例一律判断为当前危险；
- 紧急提示不编造保护令条号；
- 资料中的指令只作为待分析数据，不改变权限、不触发外发。
"""

from __future__ import annotations

import re
from typing import Any

MAX_INPUT_CHARS = 4000

# ---- 现实紧迫危险：需要「当下」标记，或明确的求救词 ----
PRESENT_MARKERS = ("现在", "此刻", "正在", "马上", "就在", "眼下", "此时", "currently")
DANGER_WORDS = (
    "救命",
    "报警",
    "打我",
    "砸门",
    "闯进来",
    "闯进",
    "伤害我",
    "要杀",
    "威胁我",
    "限制我人身",
    "不敢回家",
)
SAFETY_NOW_PATTERNS = tuple(
    re.compile(p) for p in (
        r"救命",
        r"(?:现在|此刻|正在|马上|就在|眼下|此时)[^。！？\n]{0,12}(?:危险|害怕|打我|砸门|闯进来|伤害|威胁|打)",
        r"(?:他要|他要打|他要杀|有人要)(?:打我|杀我|伤害我)",
        r"(?:砸门|闯进来|闯进我家|持刀|拿着刀)",
        r"(?:我)?(?:现在)?(?:不安全的|很危险)",
    )
)

# ---- 历史描述：不机械报警 ----
HISTORY_MARKERS = ("以前", "曾经", "之前", "那年", "当时", "过去", "上次", "历史")
VIOLENCE_WORDS = ("打过", "打我", "家暴", "暴力", "虐待", "伤害", "威胁过")

# ---- 结论类问题识别（用于收窄而不是强行回答）----
LEGAL_CONCLUSION_PATTERNS = (
    r"是不是(?:该|应该|必须|一定)",
    r"该不该",
    r"能不能(?:退|扣|要回来|全退)",
    r"必须(?:退|还)吗",
    r"违法吗",
    r"合法吗",
    r"有(?:没有)?法律依据",
    r"胜诉",
    r"起诉",
    r"诉讼时效",
    r"算不算",
    r"是不是都算",
    r"能要回来吗",
    r"有权(?:扣|不退)吗",
)
WEAR_CONCLUSION_PATTERNS = (
    r"正常损耗",
    r"自然损耗",
    r"正常使用",
    r"磨损",
    r"折旧",
    r"损耗吗",
)
DRAFT_PATTERNS = (
    r"帮我(?:写|拟|起草|发|编)",
    r"怎么(?:问|说|沟通|回)",
    r"话术",
    r"催(?:一下|他|房东)?(?:押金)?",
    r"发(?:一条|个)?(?:消息|微信|短信)",
    r"模板",
    r"照着说",
)
SOURCE_PATTERNS = (
    r"法条",
    r"法律依据",
    r"民法典",
    r"条例",
    r"哪(?:一)?条",
    r"有(?:没有)?(?:相关)?规定",
    r"依据",
    r"原文",
    r"出处",
)
CLAUSE_VALIDITY_PATTERNS = (
    r"扣(?:全部|光|所有)押金",
    r"全部押金.*扣",
    r"条款(?:有效|无效)",
    r"霸王条款",
    r"这样写(?:有效|合法)吗",
)

# ---- 资料中的指令：只作数据，不执行 ----
INJECTION_PATTERNS = (
    r"忽略(?:以上|前面|所有)(?:规则|指令|提示)",
    r"ignore\s+(?:previous|all|above)\s+instructions",
    r"把(?:所有|全部)规则设为通过",
    r"修改(?:审核|审批)(?:状态|记录)",
    r"set\s+\w+\s+(?:to\s+)?(?:approved|passed)",
    r"上传(?:全部|所有)(?:聊天记录|文件|资料)",
    r"(?:全部|所有)(?:聊天记录|文件|资料)[^。\n]{0,8}上传",
    r"上传[^。\n]{0,12}(?:全部|所有)",
    r"发送到\s*(?:http|邮箱|邮箱地址)",
    r"export\s+all",
    r"删除(?:所有|全部)(?:审核|记录)",
)

LEGAL_TOPIC_RULES = (
    (r"损耗|磨损|折旧|痕迹|印子", "这个痕迹算不算正常损耗"),
    (r"扣(?:多少|款)?|扣钱|扣减", "这笔扣款是否合理"),
    (r"退(?:还|款)?|多久|几天|什么时候", "押金应当在什么条件下退还"),
    (r"违约|违约金|提前退租", "提前退租的违约责任如何认定"),
    (r"起诉|诉讼|时效|法院", "诉讼路径与时效"),
)


def _matches(patterns, text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def analyze(message: str, attachments: list | None = None) -> dict:
    """返回本轮派生的会话信号。信号是程序计算结果，不是用户陈述的事实。"""
    text = message or ""
    signals: dict[str, Any] = {
        "safety_now": False,
        "safety_history": False,
        "asks_legal_conclusion": False,
        "asks_wear_conclusion": False,
        "asks_clause_validity": False,
        "asks_draft": False,
        "asks_source": False,
        "input_oversize": len(text) > MAX_INPUT_CHARS,
        "legal_topic": "这个问题",
    }

    has_present = any(m in text for m in PRESENT_MARKERS)
    immediate_hit = _matches(SAFETY_NOW_PATTERNS, text)
    if immediate_hit and (has_present or ("救命" in text) or ("报警" in text)):
        signals["safety_now"] = True
    elif immediate_hit:
        # 命中危险词但没有「当下」标记：不机械报警，转为确认当前是否安全
        signals["safety_history"] = True

    if not signals["safety_now"]:
        if any(h in text for h in HISTORY_MARKERS) and any(
            v in text for v in VIOLENCE_WORDS
        ):
            signals["safety_history"] = True

    if _matches(LEGAL_CONCLUSION_PATTERNS, text):
        signals["asks_legal_conclusion"] = True
    if _matches(WEAR_CONCLUSION_PATTERNS, text):
        signals["asks_wear_conclusion"] = True
    if _matches(CLAUSE_VALIDITY_PATTERNS, text):
        signals["asks_clause_validity"] = True
    if _matches(DRAFT_PATTERNS, text):
        signals["asks_draft"] = True
    if _matches(SOURCE_PATTERNS, text):
        signals["asks_source"] = True

    for pattern, topic in LEGAL_TOPIC_RULES:
        if re.search(pattern, text):
            signals["legal_topic"] = topic
            break

    injections = [p for p in INJECTION_PATTERNS if re.search(p, text, flags=re.I)]
    att_text = " ".join(
        str(a.get("extracted_text") or a.get("text") or "")
        for a in (attachments or [])
        if isinstance(a, dict)
    )
    injections += [
        f"attachment:{p}" for p in INJECTION_PATTERNS if re.search(p, att_text, flags=re.I)
    ]
    return {
        "signals": signals,
        "injection_hits": injections,
        "input_chars": len(text),
    }


def check_length(message: str) -> tuple[bool, int]:
    return (len(message or "") <= MAX_INPUT_CHARS, len(message or ""))
