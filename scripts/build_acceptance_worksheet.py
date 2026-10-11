#!/usr/bin/env python3
"""Prepare the private 80-case legal acceptance worksheet without filling legal oracles."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests/cases.jsonl"
TARGET = ROOT / "tests/LEGAL_ACCEPTANCE_WORKSHEET.md"
EXPECTED_GROUPS = {"scenario": 60, "legacy": 8, "fault": 6, "scope_privacy": 4, "urgent": 2}


def cases() -> list[dict]:
    rows = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    groups = Counter(row.get("group") for row in rows)
    splits = Counter(row.get("split") for row in rows)
    ids = [row.get("id") for row in rows]
    if (len(rows) != 80 or groups != EXPECTED_GROUPS
        or splits != {"development": 60, "holdout": 20}
        or len(set(ids)) != len(ids)
        or any(not isinstance(value, str) or not value for value in ids)
        or any(not isinstance(row.get("input"), str) or not row["input"].strip() for row in rows)):
        raise ValueError("80 组清单数量、分组、编号或输入异常，不生成复核表")
    return rows


def main() -> None:
    rows = cases()
    digest = hashlib.sha256(CASES.read_bytes()).hexdigest()
    lines = [
        "# 80 组法律与对话验收复核工作表（私人材料，未签核）", "",
        "本表只排版当前版本的测试输入，不生成法律预期，也不执行最终保留集。复核人应依据正式法源独立填写；模型输出、自评或此表的空白字段均不构成通过。", "",
        f"- 测试清单 SHA-256：`{digest}`", "- 总数：80；开发集：60；最终保留集：20。",
        "- 场景题 60、旧稿错误 8、程序故障 6、范围及隐私 4、紧急安全 2。",
        "- 最终保留集的预期答案与依据不要放进 Qwen 提示词、普通检索库或公开技能包。",
        "- 程序故障题需保存实际故障注入与阻断日志；本表只记录该用例应检查的故障类型。", "",
    ]
    for split, heading in (("development", "开发集（60 组）"), ("holdout", "最终保留集（20 组；验收前不运行）")):
        lines += [f"## {heading}", ""]
        for row in (item for item in rows if item["split"] == split):
            lines += [f"### {row['id']}｜{row['group']}", ""]
            if row.get("turns"):
                for number, turn in enumerate(row["turns"], 1):
                    lines += [f"- 第 {number} 轮用户输入：{turn}"]
            else:
                first, *rest = row["input"].splitlines()
                lines += [f"- 输入：{first}", *(f"  {line}" for line in rest)]
            lines += ["", "**由实际复核／验收人员填写**", ""]
            if row["group"] == "fault":
                lines += [
                    "- 故障注入方法与实际日志位置：＿＿＿＿＿＿＿＿＿＿＿＿",
                    "- 预期与实测的出口状态、是否出现未校验正文：＿＿＿＿＿＿＿＿＿＿＿＿",
                ]
            else:
                lines += [
                    "- 必须先核实的事实、时间及地区：＿＿＿＿＿＿＿＿＿＿＿＿",
                    "- 正式来源、条款定位、版本及效力核对日期：＿＿＿＿＿＿＿＿＿＿＿＿",
                    "- 可接受的答复要点与条件：＿＿＿＿＿＿＿＿＿＿＿＿",
                    "- 不得出现的断言或需要追问的事实：＿＿＿＿＿＿＿＿＿＿＿＿",
                    "- 多轮事实更新／更正的预期变化（适用时）：＿＿＿＿＿＿＿＿＿＿＿＿",
                ]
            lines += [
                "- 实测版本、模型参数、运行日期及结果文件：＿＿＿＿＿＿＿＿＿＿＿＿",
                "- 复核结论：□ 未审核　□ 通过　□ 退回；理由：＿＿＿＿＿＿＿＿＿＿＿＿",
                "- 复核人姓名、专业身份及日期：＿＿＿＿＿＿＿＿＿＿＿＿", "",
            ]
    TARGET.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"worksheet": str(TARGET.relative_to(ROOT)), "cases": len(rows),
                      "development": 60, "holdout": 20, "status": "未签核"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
