#!/usr/bin/env python3
"""Check candidate structure and source binding without assessing legal correctness."""
import json
from pathlib import Path

from generate_one_candidate import ARTICLES, MODEL, citation_number

ROOT = Path(__file__).resolve().parents[1]
ARRAY_FIELDS = ("conditions", "exceptions", "unknown_facts", "unsupported")
TEXT_FIELDS = ("common_question", "plain_explanation")


def main():
    index = {a["number"]: a for a in json.loads((ROOT / "sources/normalized/civil_code.json").read_text())}
    report = {"expected_scenes": len(ARTICLES), "saved_scenes": 0, "structure_pass": True,
              "professional_review": "未完成", "legal_correctness_checked": False, "scenes": {}}
    for scene, allowed in ARTICLES.items():
        path = ROOT / "rules/candidates" / f"{scene}.json"
        issues = []
        if not path.is_file():
            issues.append("候选缺失")
        else:
            report["saved_scenes"] += 1
            try:
                record = json.loads(path.read_text())
                card = record["card"]
                raw = json.loads(record["raw_content"])
                if record.get("model") != MODEL or card.get("status") != "candidate_unreviewed":
                    issues.append("模型或审核状态不符")
                if card.get("id") != scene or raw.get("id") != scene:
                    issues.append("场景编号不符")
                for key in TEXT_FIELDS:
                    if not isinstance(card.get(key), str) or not card[key].strip():
                        issues.append(f"{key} 缺失")
                for key in ARRAY_FIELDS:
                    value = card.get(key)
                    if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
                        issues.append(f"{key} 结构不符")
                if any(raw.get(key) != card.get(key) for key in TEXT_FIELDS + ARRAY_FIELDS + ("dialogue",)):
                    issues.append("候选正文与模型原始输出不一致")
                dialogue = card.get("dialogue")
                if (not isinstance(dialogue, list) or len(dialogue) != 3
                    or any(not isinstance(turn, dict) or not isinstance(turn.get("user"), str)
                           or not turn["user"].strip() or not isinstance(turn.get("assistant"), str)
                           or not turn["assistant"].strip() for turn in dialogue)):
                    issues.append("对话没有连续三轮用户与助手")
                citations = [citation_number(x) for x in raw.get("cited_articles", [])]
                if (not citations or citations != card.get("cited_articles") or any(n not in allowed for n in citations)
                    or card.get("source_article_sha256") != {str(n): index[n]["sha256"] for n in citations}):
                    issues.append("引用超界或条文哈希不符")
            except (KeyError, TypeError, ValueError, OSError) as exc:
                issues.append(f"候选文件无法完整校验：{type(exc).__name__}")
        report["scenes"][scene] = {"structure_pass": not issues, "issues": issues}
        if issues:
            report["structure_pass"] = False
    out = ROOT / "reports/CANDIDATE_AUDIT.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("expected_scenes", "saved_scenes", "structure_pass")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
