#!/usr/bin/env python3
"""Controlled answer exit for the unreleased local prototype.

Only text already present in an approved rule can pass this exit. The checker
verifies recorded state and bytes; it cannot certify legal interpretation.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import html
import json
from pathlib import Path
import re
import sys

SKILL_DIR = Path(__file__).resolve().parents[1]
# Source checkouts use skill/<name>/; hosts may install only <name>/.
# Do not infer a host configuration folder as this project's rule store.
ROOT = SKILL_DIR.parents[1] if SKILL_DIR.parent.name == "skill" else SKILL_DIR
SCENARIOS = {
    "loan_no_note": ("借条", "欠条", "转账", "借钱"),
    "loan_overdue": ("到期不还", "逾期", "不还钱", "催款", "催还"),
    "loan_no_due_date": ("没说还款", "没有还款", "还款日期", "还款期限"),
    "loan_interest_or_investment": ("利息", "投资", "入股", "收益"),
    "rent_deposit": ("押金", "保证金"),
    "rent_early_end": ("提前退租", "退租", "解约"),
    "rent_repair": ("维修", "漏水", "修房"),
    "rent_move_or_sublet": ("搬离", "搬走", "转租", "赶走", "要求搬"),
    "marital_home_timing": ("婚前房", "婚后房", "房产"),
    "marital_wages_savings": ("工资", "存款"),
    "marital_payment_source": ("首付", "还贷", "贷款"),
    "divorce_agreement_registration": ("离婚协议", "冷静期", "离婚登记"),
}
PENDING_QUESTIONS = {
    "loan_no_note": "请确认是谁向谁转钱，以及当时双方如何称呼这笔钱；有没有聊天或其他文字记录？",
    "loan_overdue": "请确认约定的还款日期，以及付款和催收的记录是否还在？",
    "loan_no_due_date": "请确认后来是否约定过日期，以及何时、通过什么方式催告过？",
    "loan_interest_or_investment": "请确认是谁向谁转钱、双方当时如何称呼这笔钱，以及有无关于收益和风险的文字约定？",
    "rent_deposit": "请确认合同如何约定押金，以及是否已办理退房交接、对方给出的扣款理由是什么？",
    "rent_early_end": "请确认租期、提前结束的约定，以及通知和交接发生在什么时候？",
    "rent_repair": "请确认故障发生的时间、合同维修约定，以及通知和处理记录是否还在？",
    "rent_move_or_sublet": "请确认合同相关条款，以及双方通知和实际搬离或转租的经过？",
    "marital_home_timing": "请确认购房、登记、结婚和付款的时间，以及有无财产约定？",
    "marital_wages_savings": "请确认款项取得的时间、来源，以及有无财产约定？",
    "marital_payment_source": "请确认首付与还贷的来源、登记情况，以及有无相关约定？",
    "divorce_agreement_registration": "请确认协议内容、登记申请和后续办理的时间，并保留相关记录？",
}
URGENT = re.compile(r"(现在|正在|马上|眼下|刚刚).{0,18}(打我|打了我|被打|挨打|殴打|威胁生命|持刀|拿刀|要杀|自伤|自杀)|(打我|打了我|被打|挨打|殴打|持刀|拿刀|要杀).{0,18}(现在|正在|马上|眼下)")
DISABLED = re.compile(r"胜诉率|必胜|保证赢|精确分房|分房比例|实时利率|诉讼费计算|具体管辖法院|自动起诉|替我提交|抚养费计算")


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(s: str) -> str:
    return re.sub(r"[\s\u3000]+", "", html.unescape(s))


def response(status: str, text: str, **extra) -> dict:
    return {"status": status, "text": text, **extra}


def collect_facts(query: dict) -> tuple[dict | None, str | None]:
    """Fold explicit user fact updates; never infer facts from conversation text."""
    if "history" not in query:
        facts = query.get("facts", {})
        if not isinstance(facts, dict):
            return None, "事实记录格式无效"
    else:
        if "facts" in query or not isinstance(query["history"], list):
            return None, "对话记录与单次事实不能混用"
        facts = {}
        for turn in query["history"]:
            if not isinstance(turn, dict) or turn.get("role") not in ("user", "assistant"):
                return None, "对话记录格式无效"
            if turn["role"] == "assistant":
                if "facts" in turn or "retract" in turn:
                    return None, "助手消息不能修改用户事实"
                continue
            update = turn.get("facts", {})
            retract = turn.get("retract", [])
            if not isinstance(update, dict) or not isinstance(retract, list) or any(
                not isinstance(key, str) or not key or not re.fullmatch(r"[a-z][a-z0-9_]*", key)
                for key in retract
            ) or any(
                not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key)
                or type(value) not in (str, int, float, bool)
                or (isinstance(value, str) and not value.strip())
                for key, value in update.items()
            ):
                return None, "用户事实更新格式无效"
            for key in retract:
                facts.pop(key, None)
            facts.update(update)
    if any(
        not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key)
        or type(value) not in (str, int, float, bool) or (isinstance(value, str) and not value.strip())
        for key, value in facts.items()
    ):
        return None, "事实字段或取值无效"
    return facts, None


def iso_date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def check_applicability(rule: dict, facts: dict) -> tuple[str | None, str | None]:
    """Require a reviewed, machine-readable case envelope before releasing fixed text."""
    envelope = rule.get("applicability")
    pattern = rule.get("fact_pattern")
    required = rule.get("required_facts")
    if not isinstance(envelope, dict) or not isinstance(pattern, dict) or not pattern:
        return "SYSTEM_ERROR", "规则缺少机器可检查的适用范围"
    start = iso_date(envelope.get("event_date_from"))
    end = iso_date(envelope.get("event_date_through"))
    regions = envelope.get("regions")
    if (not start or not end or start > end or not isinstance(regions, list) or not regions
        or any(not isinstance(region, str) or not region.strip() for region in regions)
        or not isinstance(required, list) or any(not isinstance(key, str)
               or not re.fullmatch(r"[a-z][a-z0-9_]*", key) for key in required)
        or not set(pattern).issubset(set(required))
        or any(not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key)
               or type(value) not in (str, int, float, bool) for key, value in pattern.items())):
        return "SYSTEM_ERROR", "规则适用范围或事实模式无效"
    missing = [key for key in ["event_date", "region", *required] if key not in facts]
    if missing:
        return "NEED_FACTS", "还需要确认这些事实：" + "、".join(missing[:2]) + "。"
    event_date = iso_date(facts["event_date"])
    if not event_date:
        return "NEED_FACTS", "请按 YYYY-MM-DD 补充相关事件日期。"
    if not start <= event_date <= end or facts["region"] not in regions:
        return "PENDING_REVIEW", "事件日期或地区超出这条已审核规则的适用范围，需要重新核对。"
    if any(facts[key] != value for key, value in pattern.items()):
        return "PENDING_REVIEW", "已陈述事实与这条已审核规则的前提不一致，需要重新核对。"
    allowed = {"event_date", "region", *required}
    if set(facts) - allowed:
        return "PENDING_REVIEW", "出现未由这条规则审核的新事实，需要重新核对。"
    return None, None


def check_sources(root: Path, rule: dict) -> str | None:
    manifest_path = root / "sources/SOURCE_MANIFEST.json"
    index_path = root / "sources/normalized/civil_code.json"
    if not manifest_path.is_file() or not index_path.is_file():
        return "来源清单或法条索引缺失"
    try:
        manifest = load_json(manifest_path)
        index = load_json(index_path)
    except (ValueError, OSError):
        return "来源清单或法条索引损坏"
    if not isinstance(manifest, dict) or not isinstance(index, list):
        return "来源清单或法条索引损坏"
    if len(index) != 1260 or any(not isinstance(a, dict) for a in index) or [a.get("number") for a in index] != list(range(1, 1261)):
        return "法条索引不完整"
    civil_code_source = manifest.get("civil_code")
    if not isinstance(civil_code_source, dict):
        return "民法典来源记录损坏"
    if sha_file(index_path) != civil_code_source.get("normalized_sha256"):
        return "法条索引校验失败"
    references = rule.get("references")
    if not isinstance(references, list) or not references or any(not isinstance(ref, dict) for ref in references):
        return "规则引用损坏或没有正式依据"
    for ref in references:
        source_id = ref.get("source_id")
        if not isinstance(source_id, str) or not re.fullmatch(r"[a-z0-9_]+", source_id):
            return "引用的来源编号无效"
        source = manifest.get(source_id)
        if not isinstance(source, dict) or source.get("effect_status") != "已核验有效":
            return "引用的来源未完成效力核验"
        raw_path_value = source.get("raw_path")
        if not isinstance(raw_path_value, str):
            return "来源路径无效"
        raw_rel = Path(raw_path_value)
        if raw_rel.is_absolute() or ".." in raw_rel.parts or raw_rel.parts[:2] != ("sources", "raw"):
            return "来源路径无效"
        raw_path = root / raw_rel
        if not raw_path.is_file() or sha_file(raw_path) != source.get("sha256"):
            return "引用来源的快照校验失败"
        quote = ref.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            return "引用缺少原文片段"
        if source_id == "civil_code":
            n = ref.get("article")
            if type(n) is not int or n < 1 or n > 1260 or index[n - 1].get("sha256") != ref.get("article_sha256"):
                return "条号或条文校验失败"
            article_text = index[n - 1].get("text")
            if not isinstance(article_text, str) or canonical(quote) not in canonical(article_text):
                return "民法典引文与保存原文不符"
        else:
            companion_path = root / "sources/normalized" / f"{source_id}.json"
            if not companion_path.is_file() or not source.get("normalized_sha256"):
                return "解释或条例的分条索引缺失"
            try:
                companion = load_json(companion_path)
            except (ValueError, OSError):
                return "解释或条例的分条索引损坏"
            if sha_file(companion_path) != source["normalized_sha256"]:
                return "解释或条例的分条索引校验失败"
            n = ref.get("article")
            matches = [a for a in companion if isinstance(a, dict) and a.get("number") == n] if isinstance(companion, list) and type(n) is int else []
            if (len(matches) != 1 or matches[0].get("heading") != ref.get("locator")
                or matches[0].get("sha256") != ref.get("article_sha256")):
                return "解释或条例的条号、定位或条文校验失败"
            article_text = matches[0].get("text")
            if not isinstance(article_text, str) or canonical(quote) not in canonical(article_text):
                return "解释或条例引文与保存条文不符"
            raw_text = html.unescape(re.sub(r"<[^>]+>", "", raw_path.read_text(encoding="utf-8", errors="replace")))
            if canonical(quote) not in canonical(raw_text):
                return "解释或条例引文与快照不符"
    return None


def check_rule(root: Path, rule_id: str) -> tuple[dict | None, str | None]:
    if not re.fullmatch(r"[a-z0-9-]+", rule_id):
        return None, "规则编号无效"
    path = root / "rules/approved" / f"{rule_id}.json"
    if not path.is_file():
        return None, "规则未获专业审核"
    try:
        rule = load_json(path)
        review = load_json(root / "review" / f"{rule_id}.json")
    except (ValueError, OSError):
        return None, "规则或审核记录损坏"
    if not isinstance(rule, dict) or not isinstance(review, dict):
        return None, "规则或审核记录损坏"
    if rule.get("id") != rule_id or rule.get("status") != "approved":
        return None, "规则已停用或状态不符"
    manifest_path = root / "sources/SOURCE_MANIFEST.json"
    if not manifest_path.is_file():
        return None, "来源清单缺失"
    if (review.get("rule_sha256") != sha_file(path)
        or review.get("source_manifest_sha256") != sha_file(manifest_path)
        or review.get("scope") != rule.get("scenario")
        or review.get("decision") != "approved"
        or not review.get("reviewer") or not review.get("reviewer_role") or not review.get("review_date")):
        return None, "审核记录无法对应当前规则"
    required_fields = ("approved_text", "scenario", "time_boundary", "region")
    if any(not isinstance(rule.get(field), str) or not rule[field] for field in required_fields):
        return None, "规则缺少可显示文本或适用边界"
    if any(not isinstance(rule.get(field), list) for field in ("conditions", "exceptions", "required_facts", "unsupported_conclusions")):
        return None, "规则缺少条件、例外或事实要求"
    if "{" in rule["approved_text"] or "}" in rule["approved_text"]:
        return None, "审核文本包含未填充占位符"
    source_error = check_sources(root, rule)
    return (None, source_error) if source_error else (rule, None)


def handle(query: dict, root: Path = ROOT) -> dict:
    if not isinstance(query, dict):
        return response("SYSTEM_ERROR", "输入必须是 JSON 对象。")
    question = query.get("question", "")
    if not isinstance(question, str):
        return response("SYSTEM_ERROR", "问题字段格式无效。")
    question = question.strip()
    if not question:
        return response("NEED_FACTS", "请先说说遇到的具体问题。")
    if URGENT.search(question):
        return response("URGENT", "如果你现在有人身危险，请先离开危险现场并联系当地报警或急救服务；能联系可信任的人时，请让对方陪同。等安全后再讨论财产问题。")
    if DISABLED.search(question):
        return response("OUT_OF_SCOPE", "这项精确计算或代办功能尚未开放。可以先整理关键日期、合同和付款记录，再向当地有资质的法律服务人员核实。")
    matches = [key for key, words in SCENARIOS.items() if any(w in question for w in words)]
    scenario = query.get("scenario")
    if scenario is None:
        if not matches:
            return response("OUT_OF_SCOPE", "目前仅准备自然人借贷、住房租赁和婚姻财产场景。请简要说明属于哪一类。")
        if len(matches) != 1:
            return response("NEED_FACTS", "这涉及多个可能场景。请先说最想解决的是借款、租房，还是婚姻财产中的哪一个问题？")
        scenario = matches[0]
    if not isinstance(scenario, str):
        return response("SYSTEM_ERROR", "场景字段格式无效。")
    if scenario not in SCENARIOS:
        return response("OUT_OF_SCOPE", "这个场景还未纳入首版范围。")
    rule_id = query.get("rule_id")
    if not rule_id:
        return response("PENDING_REVIEW", "这个场景的规则尚未完成专业审核，暂不能给出可靠的法律判断。" + PENDING_QUESTIONS[scenario] + "请保留相关记录，分享前遮盖无关个人信息。")
    if matches != [scenario]:
        return response("NEED_FACTS", "问题文字与选定场景没有形成唯一对应，请先确认最想解决的一个问题并补充具体事实。")
    rule, error = check_rule(root, str(rule_id))
    if error:
        status = "SYSTEM_ERROR" if any(w in error for w in ("损坏", "缺失", "校验", "不完整")) else "PENDING_REVIEW"
        return response(status, f"当前不能显示法律分析：{error}。请稍后核对资料或转交专业复核。")
    if rule["scenario"] != scenario:
        return response("PENDING_REVIEW", "选中的规则与问题场景不符，需要重新核对。")
    facts, fact_error = collect_facts(query)
    if fact_error:
        return response("NEED_FACTS", fact_error + "。")
    status, applicability_message = check_applicability(rule, facts)
    if status:
        return response(status, applicability_message)
    candidate = query.get("candidate_text")
    if candidate is None:
        return response("CANDIDATE_REQUIRED", "依据和关键事实已备齐，候选回答仍需通过受控检查后才能显示。")
    if not isinstance(candidate, str) or candidate != rule["approved_text"]:
        return response("CHECK_FAILED", "候选回答未通过检查，暂不显示相关法律结论。请核对后重新生成或转交专业复核。")
    # Exact byte-for-byte agreement is deliberate. The checker does not certify
    # that a model produced the candidate or that the approved text is legally sound.
    return response("ANSWER", rule["approved_text"], rule_id=rule_id, references=rule["references"], check_scope="结构、来源、审核记录和文本绑定检查")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", help="JSON input file; otherwise stdin")
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args()
    try:
        query = load_json(Path(args.input)) if args.input else json.load(sys.stdin)
        result = handle(query, args.root)
        print(json.dumps(result, ensure_ascii=False))
        # A host must not mistake a completed process for a passed answer gate.
        # Limited responses (including PENDING_REVIEW) are valid outputs; checker
        # and system failures are not successful executions.
        if result["status"] == "SYSTEM_ERROR":
            sys.exit(2)
        if result["status"] == "CHECK_FAILED":
            sys.exit(3)
    except (ValueError, OSError) as exc:
        print(json.dumps(response("SYSTEM_ERROR", "输入或项目文件无法读取。", detail=str(exc)), ensure_ascii=False))
        sys.exit(2)
