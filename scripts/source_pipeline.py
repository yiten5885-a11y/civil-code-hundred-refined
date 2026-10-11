#!/usr/bin/env python3
"""Fetch official source snapshots and build a quarantined Civil Code article index."""
from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
CATALOG = {
    "civil_code": ("中华人民共和国民法典", "https://www.gjxfj.gov.cn/2020-05/28/c_139952976.htm", "国家信访局转载，来源标注国家法律法规数据库"),
    "civil_code_court": ("中华人民共和国民法典（对照）", "https://www.court.gov.cn/zixun/xiangqing/233181.html", "最高人民法院"),
    "time_effect": ("民法典时间效力规定", "https://www.court.gov.cn/fabu/xiangqing/282051.html", "最高人民法院"),
    "marriage_1": ("婚姻家庭编解释（一）", "https://www.court.gov.cn/fabu/xiangqing/282071.html", "最高人民法院"),
    "marriage_2": ("婚姻家庭编解释（二）", "https://www.court.gov.cn/zixun/xiangqing/452771.html", "最高人民法院"),
    "marriage_registration_2025": ("婚姻登记条例（2025年修订）", "https://www.mee.gov.cn/zcwj/gwywj/202504/t20250410_1113983.shtml", "国务院令第804号，生态环境部转载中国政府网"),
    "marriage_registration_moj": ("婚姻登记条例（司法部行政法规库对照）", "https://xzfg.moj.gov.cn/mobile/law/detail?LawID=1766", "司法部国家行政法规库"),
    "loan_lease_2020": ("民间借贷及房屋租赁解释相关文本", "https://www.court.gov.cn/fabu/xiangqing/282621.html", "最高人民法院"),
    "contract_general": ("合同编通则解释", "https://www.court.gov.cn/fabu/xiangqing/419382.html", "最高人民法院"),
    "housing_lease": ("住房租赁条例", "https://www.mee.gov.cn/zcwj/gwywj/202507/t20250722_1123995.shtml", "国务院令第812号，生态环境部转载"),
    "anti_violence": ("反家庭暴力法", "https://www.beijing.gov.cn/zhengce/zhengcefagui/qtwj/201606/t20160628_776539.html", "北京市人民政府转载，页面标示现行有效"),
    "protection_order": ("人身安全保护令规定", "https://www.court.gov.cn/fabu/xiangqing/366021.html", "最高人民法院"),
}
KNOWN_DATES = {
    "civil_code": ("2020-05-28", "2021-01-01"),
    "civil_code_court": ("2020-05-28", "2021-01-01"),
    "marriage_2": ("2025-01-15", "2025-02-01"),
    "marriage_registration_2025": ("2025-04-06", "2025-05-10"),
    "marriage_registration_moj": ("2025-04-06", "2025-05-10"),
    "housing_lease": ("2025-07-16", "2025-09-15"),
    "anti_violence": ("2015-12-27", "2016-03-01"),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch() -> None:
    raw = ROOT / "sources/raw"
    raw.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / "sources/SOURCE_MANIFEST.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    if not isinstance(previous, dict):
        raise ValueError("来源清单格式无效")
    # Keep derived entries produced by other normalizers, such as the two
    # interpretations extracted from the Supreme Court collection. Preserve
    # existing key order so a repeat fetch does not rewrite unrelated entries.
    manifest = dict(previous)
    fresh = reused = 0
    failures = []
    for key, (title, url, publisher) in CATALOG.items():
        path = raw / f"{key}.html"
        fetched_new = not path.exists()
        if not path.exists():
            result = subprocess.run(["curl", "-fsSL", "--max-time", "35", url, "-o", str(path)], capture_output=True, text=True)
            if result.returncode:
                path.unlink(missing_ok=True)
                manifest[key] = {"title": title, "url": url, "publisher": publisher, "fetch_error": result.stderr.strip()[-500:]}
                failures.append(key)
                continue
        if not path.is_file() or path.stat().st_size == 0:
            path.unlink(missing_ok=True)
            manifest[key] = {"title": title, "url": url, "publisher": publisher, "fetch_error": "空快照"}
            failures.append(key)
            continue
        if fetched_new:
            fresh += 1
        else:
            reused += 1
        data = path.read_bytes()
        entry = {
            "title": title, "url": url, "publisher": publisher,
            "retrieved_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "raw_path": str(path.relative_to(ROOT)), "sha256": digest(data),
            "bytes": len(data),
            "promulgated_on": KNOWN_DATES.get(key, (None, None))[0],
            "effective_on": KNOWN_DATES.get(key, (None, None))[1],
            "effect_status": "待逐项核验", "review_status": "未获法律专业复核",
        }
        old = previous.get(key)
        if isinstance(old, dict) and old.get("sha256") == entry["sha256"] and old.get("url") == url:
            for field in ("normalized_sha256", "extraction_status", "effective_date_extraction", "effect_status", "review_status"):
                if field in old:
                    entry[field] = old[field]
            if old.get("effective_on"):
                entry["effective_on"] = old["effective_on"]
        manifest[key] = entry
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"downloaded": fresh, "reused_cached": reused, "failed": failures}, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


class Blocks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.current = ""
        self.lines: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "p":
            self.depth += 1
            if self.depth == 1:
                self.current = ""
        elif tag == "br" and self.depth:
            self.current += "\n"

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self.depth:
            self.depth -= 1
            if self.depth == 0:
                self.lines.extend(self.current.splitlines())
                self.current = ""

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.current += data


CN = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
UNITS = {"十": 10, "百": 100, "千": 1000}


def chinese_number(value: str) -> int:
    total = 0
    digit = 0
    for c in value:
        if c in CN:
            digit = CN[c]
        elif c in UNITS:
            total += (digit or 1) * UNITS[c]
            digit = 0
        else:
            raise ValueError(f"bad Chinese number: {value}")
    return total + digit


ARTICLE = re.compile(r"^第([零一二三四五六七八九十百千]+)条[\s\u3000]*(.*)$")
BOOK = re.compile(r"^第([一二三四五六七])编[\s\u3000]*(.*)$")
DIVISION = re.compile(r"^第([零一二三四五六七八九十百千]+)分编[\s\u3000]*(.*)$")
CHAPTER = re.compile(r"^第([零一二三四五六七八九十百千]+)章[\s\u3000]*(.*)$")
SECTION = re.compile(r"^第([零一二三四五六七八九十百千]+)节[\s\u3000]*(.*)$")
APPENDIX = re.compile(r"^附\s*则$")


def canonical(s: str) -> str:
    return re.sub(r"[\s\u3000]+", "", html.unescape(s))


def parse(path: Path, body_only: bool) -> tuple[list[dict], list[str]]:
    source = path.read_text(encoding="utf-8", errors="replace")
    if body_only:
        start = source.find('<DIV id="BodyLabel">')
        end = source.find("</DIV>", start)
        if start < 0 or end < 0:
            raise ValueError("BodyLabel absent")
        source = source[start:end]
    else:
        last = source.find("第一千二百六十条")
        close = source.find("</div>", last)
        if last < 0 or close < 0:
            raise ValueError("secondary article end absent")
        source = source[:close]
    if body_only:
        blocks = Blocks()
        blocks.feed(source)
        extracted = blocks.lines
    else:
        # The court page contains article runs outside <p>, separated by <br>.
        source = re.sub(r"<br\s*/?>|</p>", "\n", source, flags=re.I)
        source = re.sub(r"<[^>]+>", "", source)
        extracted = html.unescape(source).splitlines()
    lines = [re.sub(r"[\s\u3000]+", " ", x).strip() for x in extracted]
    lines = [x for x in lines if x]
    first = next((i for i, x in enumerate(lines) if ARTICLE.match(x)), None)
    if first is None:
        raise ValueError("no article found")
    # The contents list has no articles. Resume at the last book heading
    # before article 1, which is the actual body start in both saved pages.
    preceding_books = [i for i, x in enumerate(lines[:first]) if BOOK.match(x)]
    lines = lines[preceding_books[-1] if preceding_books else first:]
    articles: list[dict] = []
    anomalies: list[str] = []
    book = None
    book_heading = division_heading = chapter_heading = section_heading = None
    appendix = False
    for line in lines:
        m = ARTICLE.match(line)
        if m:
            n = chinese_number(m.group(1))
            if n > 1260:
                anomalies.append(f"unexpected article {n}")
            articles.append({"number": n, "book": book, "book_heading": book_heading,
                             "division_heading": division_heading, "chapter_heading": chapter_heading,
                             "section_heading": section_heading, "appendix": appendix,
                             "heading": f"第{m.group(1)}条", "paragraphs": [m.group(2)] if m.group(2) else []})
            continue
        m = BOOK.match(line)
        if m:
            book = chinese_number(m.group(1))
            book_heading = line
            division_heading = chapter_heading = section_heading = None
            appendix = False
            continue
        m = DIVISION.match(line)
        if m:
            division_heading = line
            chapter_heading = section_heading = None
            appendix = False
            continue
        m = CHAPTER.match(line)
        if m:
            chapter_heading = line
            section_heading = None
            appendix = False
            continue
        m = SECTION.match(line)
        if m:
            section_heading = line
            appendix = False
            continue
        if APPENDIX.match(line):
            division_heading = chapter_heading = section_heading = None
            appendix = True
            continue
        if line.startswith("第") and any(x in line[:12] for x in ("分编", "章", "节")):
            anomalies.append(f"unparsed outline heading: {line[:60]}")
            continue
        if articles:
            articles[-1]["paragraphs"].append(line)
    for article in articles:
        article["text"] = "\n".join(article.pop("paragraphs"))
        article["sha256"] = digest(canonical(article["text"]).encode())
    return articles, anomalies


def build() -> None:
    primary, issues = parse(ROOT / "sources/raw/civil_code.html", True)
    secondary, second_issues = parse(ROOT / "sources/raw/civil_code_court.html", False)
    counts = {}
    for a in primary:
        counts[a["number"]] = counts.get(a["number"], 0) + 1
    by_num = {a["number"]: a for a in secondary}
    differences = []
    hierarchy_differences = []
    for a in primary:
        other = by_num.get(a["number"])
        if other is None or canonical(a["text"]) != canonical(other["text"]):
            differences.append(a["number"])
        if other is None or any(canonical(str(a.get(field))) != canonical(str(other.get(field)))
                                for field in ("book", "book_heading", "division_heading",
                                              "chapter_heading", "section_heading", "appendix")):
            hierarchy_differences.append(a["number"])
    anomalies = issues + [f"secondary: {x}" for x in second_issues]
    anomalies += [f"missing {n}" for n in range(1, 1261) if n not in counts]
    anomalies += [f"duplicate {n}: {c}" for n, c in counts.items() if c != 1]
    anomalies += [f"empty {a['number']}" for a in primary if not a["text"]]
    anomalies += [f"book missing/invalid {a['number']}" for a in primary if a["book"] not in range(1, 8)]
    anomalies += [f"chapter or appendix missing {a['number']}" for a in primary if not a.get("chapter_heading") and not a.get("appendix")]
    outline_paths = {
        field: tuple(("book_heading", "division_heading", "chapter_heading", "section_heading")[:i + 1])
        for i, field in enumerate(("book_heading", "division_heading", "chapter_heading", "section_heading"))
    }
    report = {
        "primary_count": len(primary), "primary_unique": len(counts), "secondary_count": len(secondary),
        "books": sorted({a["book"] for a in primary if a["book"] is not None}),
        "hierarchy_counts": {field: len({tuple(a.get(part) for part in path) for a in primary if a.get(field)})
                             for field, path in outline_paths.items()},
        "appendix_articles": [a["number"] for a in primary if a.get("appendix")],
        "anomalies": anomalies, "cross_source_differences": differences,
        "hierarchy_differences": hierarchy_differences,
        "automated_integrity_pass": len(primary) == 1260 and len(secondary) == 1260
                                    and not anomalies and not differences and not hierarchy_differences,
        "professional_review": "未完成",
    }
    out = ROOT / "sources/normalized"
    out.mkdir(parents=True, exist_ok=True)
    index_path = out / "civil_code.json"
    index_path.write_text(json.dumps(primary, ensure_ascii=False, indent=2) + "\n")
    manifest_path = ROOT / "sources/SOURCE_MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        manifest["civil_code"]["normalized_sha256"] = digest(index_path.read_bytes())
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "SOURCE_INTEGRITY.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("anomalies", "cross_source_differences")}, ensure_ascii=False))
    print("anomalies", len(anomalies), "differences", len(differences))
    if not report["automated_integrity_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["fetch", "build"])
    args = ap.parse_args()
    {"fetch": fetch, "build": build}[args.command]()
