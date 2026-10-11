#!/usr/bin/env python3
"""Isolate two relevant judicial interpretations from the Supreme Court composite page."""
from pathlib import Path
import hashlib
import json

from normalize_companions import ARTICLE, lines_from_html, parse_source

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sources/raw/loan_lease_2020.html"
COURT = "　　最高人民法院<br />"
STARTS = {
    "urban_lease_2020": COURT + "\n　　关于审理城镇房屋租赁合同纠纷案件具体应用法律<br />",
    "private_lending_2020": COURT + "\n　　关于审理民间借贷案件适用法律若干问题的规定<br />",
}
EXPECTED = {"urban_lease_2020": 16, "private_lending_2020": 31}
TITLES = {
    "urban_lease_2020": "最高人民法院关于审理城镇房屋租赁合同纠纷案件具体应用法律若干问题的解释（合辑提取）",
    "private_lending_2020": "最高人民法院关于审理民间借贷案件适用法律若干问题的规定（合辑提取）",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(text):
    return "".join(text.split())


def main():
    source = SOURCE.read_text(encoding="utf-8", errors="replace")
    manifest_path = ROOT / "sources/SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    raw_manifest = manifest["loan_lease_2020"]
    if sha(SOURCE.read_bytes()) != raw_manifest["sha256"]:
        raise SystemExit("合辑原始快照与来源清单不符")
    out = ROOT / "sources/normalized"
    out.mkdir(parents=True, exist_ok=True)
    report = {}
    for key, marker in STARTS.items():
        if source.count(marker) != 1:
            raise SystemExit(f"{key} 标题定位不唯一")
        start = source.index(marker)
        next_court = source.find(COURT, start + len(marker))
        end = next_court if next_court >= 0 else source.find("</div>", start)
        if end < 0:
            raise SystemExit(f"{key} 未找到篇末边界")
        section = source[start:end]
        articles, anomalies = parse_source(section)
        lines = list(lines_from_html(section))
        first_article = next((i for i, line in enumerate(lines) if ARTICLE.match(line)), None)
        raw_body = "".join(canonical(line) for line in lines[first_article:]) if first_article is not None else ""
        rebuilt_body = "".join(canonical(a["heading"] + a["text"]) for a in articles)
        body_exact = bool(raw_body) and raw_body == rebuilt_body
        if not body_exact:
            anomalies.append("条文拼接与网页正文不一致")
        if len(articles) != EXPECTED[key]:
            anomalies.append(f"预计 {EXPECTED[key]} 条，实际 {len(articles)} 条")
        target = out / f"{key}.json"
        target.write_text(json.dumps(articles, ensure_ascii=False, indent=2) + "\n")
        manifest[key] = {
            "title": TITLES[key], "url": raw_manifest["url"], "publisher": raw_manifest["publisher"],
            "retrieved_utc": raw_manifest["retrieved_utc"], "raw_path": raw_manifest["raw_path"],
            "sha256": raw_manifest["sha256"], "raw_section_sha256": sha(section.encode()),
            "normalized_sha256": sha(target.read_bytes()), "promulgated_on": None,
            "effective_on": None, "effect_status": "待逐项核验",
            "review_status": "未获法律专业复核", "extraction_status": "程序暂存，待逐条核对",
        }
        report[key] = {
            "raw_source_id": "loan_lease_2020", "raw_section_sha256": sha(section.encode()),
            "normalized_sha256": sha(target.read_bytes()), "article_count": len(articles),
            "first_article": articles[0]["number"] if articles else None,
            "last_article": articles[-1]["number"] if articles else None,
            "full_body_exact": body_exact,
            "anomalies": anomalies, "effect_review": "未完成", "professional_review": "未完成",
        }
    (ROOT / "reports/LOAN_LEASE_EXTRACTION.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: {"count": v["article_count"], "anomalies": v["anomalies"]} for k, v in report.items()}, ensure_ascii=False))
    if any(v["anomalies"] or not v["full_body_exact"] for v in report.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
