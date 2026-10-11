#!/usr/bin/env python3
"""Generate one unreviewed scene card with a bounded, streaming local Qwen call."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import signal
import urllib.request

from local_ollama import local_endpoint

ROOT = Path(__file__).resolve().parents[1]
MODEL = "qwen3.8:27b"
ARTICLES = {
    "loan_no_note": [667, 679],
    "loan_overdue": [675, 676],
    "loan_no_due_date": [675, 676],
    "loan_interest_or_investment": [667, 679, 680],
    "rent_deposit": [703, 733],
    "rent_early_end": [563, 566, 577, 730],
    "rent_repair": [712, 713],
    "rent_move_or_sublet": [716, 725, 730, 733],
    "marital_home_timing": [1062, 1063],
    "marital_wages_savings": [1062, 1063],
    "marital_payment_source": [1062, 1063, 1065],
    "divorce_agreement_registration": [1076, 1077],
}
FOCUS = {
    "loan_no_note": "没有借条但有转账时，钱的性质、交付与其他证据不能只凭转账自动认定。",
    "loan_overdue": "约定还款期限已到但未归还，需确认期限、催收及约定内容。",
    "loan_no_due_date": "借款未约定还款日期，需确认能否确定期限及催告经过。",
    "loan_interest_or_investment": "争议在借款还是投资及利息约定；所给条文不足以直接认定交易性质，要问当时约定和实际履行。",
    "rent_deposit": "退房后押金未退；所给条文没有直接规定押金自动退还，应核对合同、交接和损失记录。",
    "rent_early_end": "承租人想提前退租；区分固定期限与不定期、约定解除及违约责任，不要只讨论房东解除。",
    "rent_repair": "出租房屋需维修，核对损坏原因、通知、维修约定和处理经过。",
    "rent_move_or_sublet": "房东要求搬离或承租人想转租；分清所有权变动、不定期租赁和转租同意。",
    "marital_home_timing": "婚前或婚后购房，先核对购买、结婚、登记和付款时间，不直接认定产权。",
    "marital_wages_savings": "工资和存款归属，核对取得时间、来源与书面财产约定。",
    "marital_payment_source": "争议在房屋首付和还贷资金来源，核对资金形成时间、来源、书面约定及登记，不能只谈财产类别。",
    "divorce_agreement_registration": "离婚协议和登记时间，区分签协议、提交申请、冷静期及领证事实。",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timed_out(signum, frame):
    raise TimeoutError("本地模型请求超过240秒总时限")


def citation_number(value):
    if type(value) is int:
        return value
    if isinstance(value, str):
        match = re.fullmatch(r"(?:民法典)?第(\d{1,4})条", value.strip())
        if match:
            return int(match.group(1))
    raise ValueError("候选条号格式不受支持")


def candidate_counts(out):
    saved = ready = 0
    for path in out.glob("*.json"):
        saved += 1
        try:
            dialogue = json.loads(path.read_text())["card"]["dialogue"]
            if len(dialogue) == 3 and all(isinstance(turn, dict) for turn in dialogue):
                ready += 1
        except (KeyError, TypeError, ValueError, OSError):
            pass
    return saved, ready


def save_candidate(content, scene, numbers, index, started_utc, out, recovered=False, replace=False):
    card = json.loads(content)
    dialogue = card.get("dialogue")
    if (card.get("id") != scene or not isinstance(dialogue, list) or len(dialogue) != 3
        or any(not isinstance(turn, dict) or not isinstance(turn.get("user"), str)
               or not turn["user"].strip() or not isinstance(turn.get("assistant"), str)
               or not turn["assistant"].strip() for turn in dialogue)):
        raise ValueError("场景编号或三轮对话结构不符")
    if not isinstance(card.get("cited_articles"), list) or not card["cited_articles"]:
        raise ValueError("候选缺少条文引用")
    citations = [citation_number(value) for value in card["cited_articles"]]
    if any(n not in numbers for n in citations):
        raise ValueError("候选引用越出提供的条文")
    card["cited_articles"] = citations
    card["status"] = "candidate_unreviewed"
    card["source_id"] = "civil_code"
    card["source_article_sha256"] = {str(n): index[n]["sha256"] for n in citations}
    record = {"model": MODEL, "started_utc": started_utc, "finished_utc": utc_now(),
              "parameters": {"temperature": 0.2, "num_ctx": 3072, "num_predict": 700, "think": False},
              "card": card, "raw_content": content, "recovered_from_partial": recovered,
              "note": "模型候选，未获法律专业审核"}
    target = out / f"{scene}.json"
    if target.exists():
        if not replace:
            raise ValueError("已有候选；如需重生成请明确使用 --replace")
        backup = out / "versions" / f"{scene}.{utc_now().replace(':', '-')}.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=ARTICLES)
    parser.add_argument("--recover-partial", action="store_true", help="解析本次先前保存的完整响应，不再次调用模型")
    parser.add_argument("--replace", action="store_true", help="保留旧版到 versions 后重生成该场景")
    parser.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
                        help="本机 Ollama 回环地址；默认读取 OLLAMA_HOST")
    args = parser.parse_args()
    scene = args.scenario
    index = {article["number"]: article for article in json.loads((ROOT / "sources/normalized/civil_code.json").read_text())}
    integrity = json.loads((ROOT / "reports/SOURCE_INTEGRITY.json").read_text())
    if not integrity.get("automated_integrity_pass"):
        raise SystemExit("民法典文本自动完整性检查未通过")
    numbers = ARTICLES[scene]
    excerpts = "\n".join(f"民法典第{n}条：{index[n]['text']}" for n in numbers)
    prompt = (
        "你是候选草稿助手。只依据下列原文，给场景 " + scene + " 写一张待专业审核的紧凑 JSON 卡。"
        "问题重点：" + FOCUS[scene] + "。"
        "仅有这些字段：id、common_question、plain_explanation、conditions、exceptions、unknown_facts、"
        "unsupported、cited_articles、dialogue。id 必须与场景相同；conditions、exceptions、unknown_facts、"
        "unsupported、cited_articles、dialogue 都是数组；dialogue 恰好三个对象，每个对象有 user 和 assistant 字符串。"
        "第二轮用户要补充会改变判断的事实，第三轮用户要更正一个先前前提或只追问一点；每轮回复不超过60字。"
        "条文没有覆盖的例外写‘待核查’，不可凭记忆补法条或断定个案结果。"
        "所有内容均是未审草稿。\n" + excerpts
    )
    body = json.dumps({
        "model": MODEL, "messages": [{"role": "user", "content": prompt}],
        "stream": True, "format": "json", "think": False,
        "options": {"temperature": 0.2, "num_ctx": 3072, "num_predict": 700},
    }, ensure_ascii=False).encode()
    out = ROOT / "rules/candidates"
    out.mkdir(parents=True, exist_ok=True)
    partial = out / f"{scene}.partial.txt"
    state_path = ROOT / "STATE.json"
    if args.recover_partial:
        prior = json.loads(state_path.read_text())
        if prior.get("current_task") != scene or prior.get("model_generating") or not partial.is_file():
            raise SystemExit("没有可恢复的该场景完整响应")
        save_candidate(partial.read_text(), scene, numbers, index, prior["started_utc"], out, recovered=True, replace=args.replace)
        saved, ready = candidate_counts(out)
        prior.update({"failure": None, "finished_utc": utc_now(), "last_output_utc": utc_now(),
                      "completed_scenes": saved, "three_round_scenes": ready, "pending_review_count": saved,
                      "total_scenes": len(ARTICLES), "next": "继续生成其他场景，再提交专业复核"})
        state_path.write_text(json.dumps(prior, ensure_ascii=False, indent=2) + "\n")
        partial.unlink()
        print(json.dumps({"scenario": scene, "status": "candidate_unreviewed", "recovered": True}, ensure_ascii=False))
        return
    try:
        endpoint = local_endpoint(args.host)
    except ValueError as exc:
        parser.exit(2, f"本地模型地址无效：{exc}\n")
    request = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"})
    saved, ready = candidate_counts(out)
    state = {"phase": "P2候选规则", "current_task": scene, "model_generating": True,
             "started_utc": utc_now(), "failure": None, "pending_review": True,
             "completed_scenes": saved, "three_round_scenes": ready,
             "pending_review_count": saved, "total_scenes": len(ARTICLES),
             "last_output_utc": None, "next": "保存候选并继续生成"}
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    chunks = []
    signal.signal(signal.SIGALRM, timed_out)
    try:
        signal.setitimer(signal.ITIMER_REAL, 240)
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=240) as response:
            for line in response:
                event = json.loads(line)
                if event.get("error"):
                    raise RuntimeError(event["error"])
                piece = event.get("message", {}).get("content", "")
                if piece:
                    chunks.append(piece)
                    partial.write_text("".join(chunks))
                if event.get("done"):
                    break
        content = "".join(chunks)
        save_candidate(content, scene, numbers, index, state["started_utc"], out, replace=args.replace)
        partial.unlink(missing_ok=True)
        saved, ready = candidate_counts(out)
        state.update({"model_generating": False, "finished_utc": utc_now(), "last_output_utc": utc_now(),
                      "completed_scenes": saved, "three_round_scenes": ready, "pending_review_count": saved,
                      "next": "继续生成其他场景，再提交专业复核"})
        print(json.dumps({"scenario": scene, "status": "candidate_unreviewed"}, ensure_ascii=False))
    except Exception as exc:
        state.update({"model_generating": False, "finished_utc": utc_now(),
                      "failure": f"{type(exc).__name__}: {exc}",
                      "next": "检查当前模型占用和残留片段，再决定是否重试"})
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
