#!/usr/bin/env python3
"""Build a private, unsigned review worksheet from the twelve Qwen candidates."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from audit_candidates import main as audit
from audit_supplements import main as audit_supplements
from generate_one_candidate import ARTICLES

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "rules/candidates/REVIEW_WORKSHEET.md"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bullets(items: list[str]) -> list[str]:
    return [f"- {item.replace(chr(10), ' ')}" for item in items]


def quote(value: str) -> list[str]:
    return ["> " + line for line in value.splitlines()] or ["> "]


def main() -> None:
    audit()
    audit_supplements()
    result = json.loads((ROOT / "reports/CANDIDATE_AUDIT.json").read_text())
    supplement_report = json.loads((ROOT / "reports/SUPPLEMENT_AUDIT.json").read_text())["supplements"]
    if not result["structure_pass"] or result["saved_scenes"] != len(ARTICLES):
        raise SystemExit("候选结构未通过检查，不能生成审核工作表")
    manifest_path = ROOT / "sources/SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    index_path = ROOT / "sources/normalized/civil_code.json"
    if sha(index_path) != manifest["civil_code"]["normalized_sha256"]:
        raise SystemExit("民法典分条索引与来源清单哈希不符")
    index = {entry["number"]: entry for entry in json.loads(index_path.read_text())}
    lines = [
        "# 十二场景法律专业复核工作表（私人材料，未签核）",
        "",
        "本文件由候选卡自动排版，仅用于逐项人工审查。勾选或填写本表本身不会把规则转为已审定；须由真实法律专业人员核对正式来源及现行效力、明确审核范围，并形成独立签核记录。",
        "",
        f"- 候选场景数：{len(ARTICLES)}",
        f"- 来源清单 SHA-256：`{sha(manifest_path)}`",
        f"- 本地民法典索引 SHA-256：`{sha(index_path)}`",
        f"- 民法典来源状态：{manifest['civil_code']['effect_status']}（需复核人员核实）",
        f"- 正式来源入口：{manifest['civil_code']['url']}",
        "- 其他待核查表达：见同包 `rules/candidates/REVIEW_FLAGS.md`。",
        "- 补充候选结构检查未通过的场景：" + "、".join(
            scene for scene, item in supplement_report.items() if not item["structure_pass"]
        ) + "；这些稿件仅供指出错误和退回修改。",
        "- 各场景配套资料覆盖差距：见同包 `plan/SOURCE_COVERAGE.md`。",
        "- 本地检索押金一词的定位记录：见同包 `reports/SOURCE_SEARCH_SMOKE.json`；命中不等于法律适用。",
        "",
    ]
    for scene in ARTICLES:
        path = ROOT / "rules/candidates" / f"{scene}.json"
        record = json.loads(path.read_text())
        card = record["card"]
        lines += [
            f"## {scene} — {card['common_question']}",
            "",
            f"候选文件 SHA-256：`{sha(path)}`；模型：`{record['model']}`；状态：`{card['status']}`。",
            "",
            "### 候选白话解释（未审核）",
            "",
            *quote(card["plain_explanation"]),
            "",
            "### 候选所列条件、例外与未知事实（均需核查）",
            "",
            "**条件**",
            *bullets(card["conditions"]),
            "",
            "**例外**",
            *bullets(card["exceptions"]),
            "",
            "**尚需事实**",
            *bullets(card["unknown_facts"]),
            "",
            "**不能推出的结论**",
            *bullets(card["unsupported"]),
            "",
            "### 候选引用的民法典条文（请到正式入口复核上下文和效力）",
            "",
        ]
        for number in card["cited_articles"]:
            article = index[number]
            if card["source_article_sha256"].get(str(number)) != article["sha256"]:
                raise SystemExit(f"{scene} 引用第 {number} 条的哈希不符")
            lines += [
                f"**{article['heading']}**，索引条文 SHA-256：`{article['sha256']}`",
                "",
                *quote(article["text"]),
                "",
            ]
        supplement_path = ROOT / "rules/candidates/supplements" / f"{scene}.json"
        if supplement_path.is_file():
            supplement = json.loads(supplement_path.read_text())
            draft = supplement["card"]
            supplement_audit = supplement_report[scene]
            problems = []
            if supplement_audit["uncited_article_mentions"]:
                problems.append("漏列条号：" + "、".join(map(str, supplement_audit["uncited_article_mentions"])))
            if not supplement_audit["third_turn_correction_signal"]:
                problems.append("第三轮用户未明确更正前提")
            elif not supplement_audit["third_turn_correction_binding"]:
                problems.append("第三轮未逐字撤回先前用户事实")
            audit_text = ("结构检查未通过；" + "；".join(problems) if problems
                          else "结构检查通过；法律含义仍待专业复核")
            if supplement_audit.get("known_error_codes"):
                audit_text += "；命中已知错误表达：" + "、".join(supplement_audit["known_error_codes"])
            lines += [
                "### 多来源补充候选（仍未审核）",
                "",
                f"补充候选 SHA-256：`{sha(supplement_path)}`；输入原文哈希已核对；{audit_text}。",
                "",
                "**补充候选白话解释**",
                *quote(draft["plain_explanation"]),
                "",
                "**相比旧稿声称的变化（逐项核查）**",
                *bullets(draft["changes_from_prior"]),
                "",
                "**补充候选输入的原文（核对正式入口及适用范围）**",
                "",
            ]
            for ref in supplement["input_evidence"]:
                source_id, number = ref["source_id"], ref["article"]
                companion = {entry["number"]: entry for entry in json.loads(
                    (ROOT / "sources/normalized" / f"{source_id}.json").read_text())}
                article = companion[number]
                if article["sha256"] != ref["article_sha256"]:
                    raise SystemExit(f"{scene}: 补充候选输入条文哈希不符")
                lines += [
                    f"{manifest[source_id]['title']} {article['heading']}；条文 SHA-256：`{article['sha256']}`；来源：{manifest[source_id]['url']}",
                    "",
                    *quote(article["text"]),
                    "",
                ]
            lines += [
                "**补充候选引用**",
                *[f"- {ref['source_id']} 第 {ref['article']} 条" for ref in draft["cited_sources"]],
                "",
                "**补充候选三轮示例（逐轮审核）**",
                "",
            ]
            for number, turn in enumerate(draft["dialogue"], 1):
                lines += [f"- 第 {number} 轮用户：{turn['user']}",
                          f"- 第 {number} 轮候选回答：{turn['assistant']}"]
            note = ROOT / "rules/candidates/supplements" / f"{scene}.REVIEW.md"
            if note.is_file():
                lines += ["", f"**已记录待纠错点，请先阅读同包 `rules/candidates/supplements/{scene}.REVIEW.md`。**"]
            lines += ["", "**此补充候选仍需单独核对条件、例外、时间、地区和建议动作，不能仅凭本表签核。**", ""]
        lines += ["### 候选连续三轮对话（逐轮审核）", ""]
        for turn_number, turn in enumerate(card["dialogue"], 1):
            lines += [
                f"**第 {turn_number} 轮用户：** {turn['user']}",
                "",
                f"**第 {turn_number} 轮候选回答：** {turn['assistant']}",
                "",
                f"- [ ] 第 {turn_number} 轮正确使用了此前已知事实及本轮更正；没有扩大法律结论。",
                "",
            ]
        lines += [
            "### 复核人员填写（不得由模型代填）",
            "",
            "- [ ] 已从正式来源核对文本、颁布与施行日期、修正或废止状态；记录核对入口和日期。",
            "- [ ] 已核对所需配套规定、司法解释、主要例外及事实时间适用。",
            "- [ ] 已逐项核对候选白话解释、条件、例外、未知事实与不能推出的结论。",
            "- [ ] 已按实际问题核定适用地区、事件日期区间与可机器核对的事实模式。",
            "- [ ] 已检查三轮问答的事实更正、追问数量、答案强度及普通人可理解性。",
            "",
            "审核决定：□ 退回修改　□ 限定范围通过　□ 未完成审核",
            "",
            "审核范围及理由：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "",
            "须修改的候选字段与三轮示例：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "",
            "批准的固定回答原文（如通过）：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "",
            "允许的事件日期区间／地区／事实模式：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "",
            "复核人姓名、专业身份及日期：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "",
            "复核时确认的来源清单 SHA-256：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "",
            "---",
            "",
        ]
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"worksheet": str(TARGET.relative_to(ROOT)), "scenes": len(ARTICLES),
                      "status": "未签核"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
