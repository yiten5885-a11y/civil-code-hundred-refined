#!/usr/bin/env python3
"""Compare the lending text extracted from the 2020 composite with a second court page."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone

from normalize_companions import parse_source

ROOT = Path(__file__).resolve().parents[1]
URL = "https://cicc.court.gov.cn/html/1/218/62/84/12844.html"
RAW = ROOT / "sources/raw/private_lending_cicc.html"
INDEX = ROOT / "sources/normalized/private_lending_cicc.json"
PRIMARY = ROOT / "sources/normalized/private_lending_2020.json"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(text):
    return re.sub(r"[\s\u3000]+", "", text)


def main():
    if not RAW.is_file():
        RAW.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["curl", "-fsSL", "--max-time", "35", URL, "-o", str(RAW)], capture_output=True, text=True)
        if result.returncode:
            RAW.unlink(missing_ok=True)
            raise SystemExit(result.stderr.strip()[-500:])
    source = RAW.read_text(encoding="utf-8", errors="replace")
    marker = '<article class="essay-content">'
    if source.count(marker) != 1:
        raise SystemExit("第二来源正文容器定位不唯一")
    start = source.index(marker)
    end = source.find("</article>", start)
    if end < 0:
        raise SystemExit("第二来源正文容器未闭合")
    secondary, anomalies = parse_source(source[start:end])
    primary = json.loads(PRIMARY.read_text())
    by_number = {a["number"]: a for a in secondary}
    differences = [a["number"] for a in primary if a["number"] not in by_number or canonical(a["text"]) != canonical(by_number[a["number"]]["text"])]
    if len(secondary) != 31:
        anomalies.append(f"第二来源预计31条，实际{len(secondary)}条")
    if len(by_number) != len(secondary):
        anomalies.append("第二来源条号重复")
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(secondary, ensure_ascii=False, indent=2) + "\n")
    report = {"primary_source_id": "private_lending_2020", "second_url": URL,
              "second_raw_sha256": sha(RAW.read_bytes()), "second_normalized_sha256": sha(INDEX.read_bytes()),
              "primary_count": len(primary), "second_count": len(secondary),
              "cross_source_differences": differences, "anomalies": anomalies,
              "automated_text_match": len(primary) == len(secondary) == 31 and not differences and not anomalies,
              "effect_review": "未完成", "professional_review": "未完成"}
    (ROOT / "reports/LENDING_CROSSCHECK.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    manifest_path = ROOT / "sources/SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["private_lending_cicc"] = {
        "title": "最高人民法院关于审理民间借贷案件适用法律若干问题的规定（对照）",
        "url": URL, "publisher": "最高人民法院国际商事法庭转载，页面来源标注法信",
        "retrieved_utc": datetime.fromtimestamp(RAW.stat().st_mtime, timezone.utc).isoformat(),
        "raw_path": str(RAW.relative_to(ROOT)), "sha256": report["second_raw_sha256"],
        "normalized_sha256": report["second_normalized_sha256"],
        "promulgated_on": None, "effective_on": None, "effect_status": "待逐项核验",
        "review_status": "未获法律专业复核",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"count": len(secondary), "differences": differences, "anomalies": anomalies}, ensure_ascii=False))
    if not report["automated_text_match"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
