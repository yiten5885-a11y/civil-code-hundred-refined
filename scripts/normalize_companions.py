#!/usr/bin/env python3
"""Extract provisional article units from single-document official HTML snapshots."""
from pathlib import Path
import hashlib
import html
import json
import re

ROOT = Path(__file__).resolve().parents[1]
SINGLE = ("time_effect", "marriage_1", "marriage_2", "marriage_registration_2025", "marriage_registration_moj", "contract_general", "housing_lease", "anti_violence", "protection_order")
ARTICLE = re.compile(r"^第([零一二三四五六七八九十百千]+)条[\s\u3000]*(.*)$")
CN = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
UNIT = {"十": 10, "百": 100, "千": 1000}
FOOTER = ("责任编辑", "相关报道", "相关新闻", "新闻链接", "相关链接", "相关阅读推荐", "分享：", "[大][中][小]", "中国共产党新闻网", "中华人民共和国最高人民法院 版权所有", "中华人民共和国司法部 版权所有", "版权所有", "网站地图")
SECTION_LINE = re.compile(r"^[一二三四五六七八九十百]+、[^。！？；，]{2,25}$")
# These headings occur between articles in the saved official pages. Keep the
# exact list narrow so an article's own numbered prose is never silently cut.
SECTION_HEADINGS = {
    "time_effect": ("二、溯及适用的具体规定", "三、衔接适用的具体规定", "四、附则"),
    "marriage_1": ("二、结婚", "三、夫妻关系", "四、父母子女关系", "五、离婚", "六、附则"),
    "contract_general": ("二、合同的订立", "三、合同的效力", "四、合同的履行", "五、合同的保全",
                         "六、合同的变更和转让", "七、合同的权利义务终止", "八、违约责任", "九、附则"),
}


def number(value):
    total = digit = 0
    for c in value:
        if c in CN:
            digit = CN[c]
        elif c in UNIT:
            total += (digit or 1) * UNIT[c]
            digit = 0
        else:
            raise ValueError(value)
    return total + digit


def lines_from_html(source):
    source = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", source, flags=re.I | re.S)
    source = re.sub(r"<br\s*/?>|</p>|</div>", "\n", source, flags=re.I)
    source = html.unescape(re.sub(r"<[^>]+>", "", source))
    for line in source.splitlines():
        line = re.sub(r"[\s\u3000]+", " ", line).strip()
        if line:
            yield line


def parse_source(source, section_headings=()):
    lines = list(lines_from_html(source))
    first = next((i for i, line in enumerate(lines) if ARTICLE.match(line)), None)
    if first is None:
        return [], ["未找到以条号开头的行"]
    articles = []
    for line in lines[first:]:
        if any(line.startswith(marker) for marker in FOOTER):
            break
        if line in section_headings:
            continue
        match = ARTICLE.match(line)
        if match:
            articles.append({"number": number(match.group(1)), "heading": "第" + match.group(1) + "条", "paragraphs": [match.group(2)] if match.group(2) else []})
        elif articles and not re.match(r"^第[零一二三四五六七八九十百千]+[章节编]", line):
            articles[-1]["paragraphs"].append(line)
    anomalies = []
    nums = [x["number"] for x in articles]
    if nums != list(range(1, max(nums, default=0) + 1)):
        anomalies.append("条号不连续、重复或非升序")
    for a in articles:
        a["text"] = "\n".join(a.pop("paragraphs"))
        a["sha256"] = hashlib.sha256(re.sub(r"[\s\u3000]+", "", a["text"]).encode()).hexdigest()
        if len(a["text"]) < 5:
            anomalies.append(f"第{a['number']}条可能为空或截断")
    return articles, anomalies


def parse(path, section_headings=()):
    return parse_source(path.read_text(encoding="utf-8", errors="replace"), section_headings)


def main():
    manifest_path = ROOT / "sources/SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    report = {}
    out = ROOT / "sources/normalized"
    out.mkdir(parents=True, exist_ok=True)
    for key in SINGLE:
        path = ROOT / "sources/raw" / f"{key}.html"
        if not path.is_file():
            report[key] = {"error": "快照缺失"}
            continue
        headings = SECTION_HEADINGS.get(key, ())
        articles, anomalies = parse(path, headings)
        page_lines = list(lines_from_html(path.read_text(encoding="utf-8", errors="replace")))
        excluded = [line for line in page_lines if line in headings]
        if sorted(excluded) != sorted(headings):
            anomalies.append("已登记分节标题在页面中缺失或重复")
        stray = sorted({line for article in articles for line in article["text"].splitlines()
                        if SECTION_LINE.fullmatch(line)})
        if stray:
            anomalies.append("疑似分节标题混入条文：" + "、".join(stray))
        effective = re.findall(r"自(\d{4})年(\d{1,2})月(\d{1,2})日起施行", articles[-1]["text"]) if articles else []
        effective_on = f"{int(effective[0][0]):04d}-{int(effective[0][1]):02d}-{int(effective[0][2]):02d}" if len(effective) == 1 else None
        if effective_on and manifest[key].get("effective_on") not in (None, effective_on):
            anomalies.append("清单施行日期与末条文本不符")
        target = out / f"{key}.json"
        target.write_text(json.dumps(articles, ensure_ascii=False, indent=2) + "\n")
        manifest[key]["normalized_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest[key]["extraction_status"] = "程序暂存，待逐条核对"
        if effective_on:
            manifest[key]["effective_on"] = effective_on
            manifest[key]["effective_date_extraction"] = "末条自动识别，待逐项核对"
        report[key] = {"article_count": len(articles), "unique": len({a["number"] for a in articles}),
                       "section_headings_excluded": excluded,
                       "effective_on_from_last_article": effective_on, "anomalies": anomalies, "professional_review": "未完成"}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "reports/COMPANION_EXTRACTION.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: {"count": v.get("article_count"), "anomalies": len(v.get("anomalies", []))} for k, v in report.items()}, ensure_ascii=False))
    if any(v.get("error") or v.get("anomalies") or not v.get("article_count") for v in report.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
