#!/usr/bin/env python3
"""Generate unreviewed drafting cards from local Ollama and verified source excerpts."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import sys
import urllib.request

from local_ollama import local_endpoint

ROOT = Path(__file__).resolve().parents[1]
MODEL = "qwen3.8:27b"
GROUPS = {
    "loan": ({
        "loan_no_note": "没有借条但有转账",
        "loan_overdue": "说好还款日却不还",
        "loan_no_due_date": "没有说清还款日期",
        "loan_interest_or_investment": "利息、借款与投资性质有争议",
    }, [188, 195, 667, 668, 675, 676, 679, 680]),
    "rent": ({
        "rent_deposit": "退租后押金不退",
        "rent_early_end": "提前退租",
        "rent_repair": "房屋维修",
        "rent_move_or_sublet": "房东要求搬离或转租争议",
    }, [703, 704, 707, 708, 709, 710, 711, 715, 716, 722, 729, 733]),
    "marriage": ({
        "marital_home_timing": "婚前婚后房产",
        "marital_wages_savings": "工资与存款",
        "marital_payment_source": "首付与还贷来源",
        "divorce_agreement_registration": "离婚财产约定和登记时间",
    }, [1062, 1063, 1065, 1076, 1077, 1087]),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def deadline_exceeded(signum, frame):
    raise TimeoutError("本地模型请求超过240秒总时限")


def main() -> None:
    signal.signal(signal.SIGALRM, deadline_exceeded)
    endpoint = local_endpoint(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    index = {a["number"]: a for a in json.loads((ROOT / "sources/normalized/civil_code.json").read_text())}
    integrity = json.loads((ROOT / "reports/SOURCE_INTEGRITY.json").read_text())
    if not integrity.get("automated_integrity_pass"):
        raise SystemExit("民法典文本完整性检查未通过")
    out = ROOT / "rules/candidates"
    out.mkdir(parents=True, exist_ok=True)
    state_path = ROOT / "STATE.json"
    selected = sys.argv[1:] or list(GROUPS)
    for domain in selected:
        scenarios, numbers = GROUPS[domain]
        state = {"phase": "P2候选规则", "current_task": domain, "model_generating": True, "completed_groups": len(list(out.glob("*.json"))), "total_groups": 3, "pending_review": True, "last_output_utc": None, "failure": None, "next": "保存候选并进入专业复核"}
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        excerpts = "\n".join(f"民法典第{n}条：{index[n]['text']}" for n in numbers)
        prompt = f"""你是法律内容草稿助手。只根据提供的民法典条文生成候选内容，不得宣称已审核，不得补写司法解释或确定个案结果。场景：{json.dumps(scenarios, ensure_ascii=False)}。
输出紧凑 JSON：cards 数组恰好四项。每项含 id、common_question、plain_explanation、conditions（1项）、exceptions（1项）、unknown_facts（2项）、unsupported（1项）、cited_articles（整数数组）、dialogue（三轮简短用户问题与候选回应，每轮一个字符串）。每项解释不超过80字，每轮对话不超过45字。引用只用给出的条号，拿不准写待复核；不得捏造个案事实。所有内容均是未审草稿。
条文：\n{excerpts}"""
        req = urllib.request.Request(endpoint, data=json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False, "format": "json", "think": False, "options": {"temperature": 0.2, "num_ctx": 4096, "num_predict": 1100}}).encode(), headers={"Content-Type": "application/json"})
        started = now()
        try:
            signal.setitimer(signal.ITIMER_REAL, 240)
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=240) as resp:
                payload = json.load(resp)
            signal.setitimer(signal.ITIMER_REAL, 0)
            content = payload.get("message", {}).get("content", "")
            (out / f"{domain}.raw.txt").write_text(content)
            draft = json.loads(content)
            cards = draft.get("cards", [])
            if {c.get("id") for c in cards} != set(scenarios):
                raise ValueError("候选卡数量或场景编号不符")
            for card in cards:
                if any(n not in numbers for n in card.get("cited_articles", [])):
                    raise ValueError("候选引用越出给定条文")
                card["status"] = "candidate_unreviewed"
                card["source_id"] = "civil_code"
                card["source_article_sha256"] = {str(n): index[n]["sha256"] for n in card.get("cited_articles", [])}
            record = {"model": MODEL, "started_utc": started, "finished_utc": now(), "parameters": {"temperature": 0.2, "num_ctx": 4096, "num_predict": 1100, "think": False}, "cards": cards, "raw_content": content, "note": "模型候选，未获法律专业审核"}
            (out / f"{domain}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            state.update({"model_generating": False, "completed_groups": len(list(out.glob("*.json"))), "last_output_utc": now()})
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            print(domain, "cards", len(cards), "seconds", round(payload.get("total_duration", 0) / 1e9, 1), flush=True)
        except Exception as exc:
            signal.setitimer(signal.ITIMER_REAL, 0)
            state.update({"model_generating": False, "failure": f"{type(exc).__name__}: {exc}", "next": "核查本地模型返回并重试当前组"})
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            print(domain, "failed", repr(exc), file=sys.stderr, flush=True)
            raise


if __name__ == "__main__":
    main()
