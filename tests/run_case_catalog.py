#!/usr/bin/env python3
"""Run only development cases through the currently closed answer gate."""
import importlib.util
import json
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("answer", ROOT / "skill/civil-code-plain-answers/scripts/answer.py")
answer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(answer)


def main():
    rows = [json.loads(line) for line in (ROOT / "tests/cases.jsonl").read_text().splitlines()]
    results = []
    for row in rows:
        if row["split"] == "holdout" or row["group"] == "fault":
            continue
        turns = row.get("turns", [row["input"]])
        history = []
        turn_results = []
        for prompt in turns:
            history.append({"role": "user", "content": prompt})
            response = answer.handle({"question": prompt,
                                      **({"scenario": row["scenario"]} if row.get("scenario") else {}),
                                      "history": history}, ROOT)
            turn_results.append({"status": response["status"], "text": response["text"]})
            assert response["status"] != "ANSWER", "Unreviewed legal answer escaped in a turn"
            history.append({"role": "assistant", "content": response["text"]})
        results.append({"id": row["id"], "status": turn_results[-1]["status"],
                        "text": turn_results[-1]["text"], "turn_results": turn_results})
    counts = dict(Counter(x["status"] for x in results))
    assert "ANSWER" not in counts, "No production rule was reviewed; legal answer must remain closed"
    report = {"tested": len(results), "multi_turn_development_cases": sum(len(x["turn_results"]) == 3 for x in results),
              "holdout_not_run": sum(x["split"] == "holdout" for x in rows), "faults_tested_separately": True,
              "status_counts": counts, "legal_acceptance": "未运行；法律预期未审定",
              "multi_turn_scope": "仅检查每轮关闭状态；自由文本事实理解与跨轮记忆未验收", "results": results}
    (ROOT / "reports/CASE_DEVELOPMENT_RUN.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"tested": len(results), "status_counts": counts, "holdout_not_run": report["holdout_not_run"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
