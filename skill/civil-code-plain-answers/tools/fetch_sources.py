#!/usr/bin/env python3
"""法源采集工具（G01 用）。

职责：
1. 从登记的官方入口取得原始页面并保存字节快照；
2. 抽取条、款、项原文，生成规范化引用文本；
3. 计算 FILE_BYTES 与 CANONICAL_TEXT 摘要，写入 sources/<id>/meta.json。

约束（对应规格 7.2）：
- 只做有记录的空白规范化，不删除否定词、但书、款项；
- 不使用 NFKC 等兼容归一化改写数字或法律引用含义；
- OCR 或异常字符必须核清后才进入可引用集，本工具遇到可疑字符会记入 warnings。
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCES_DIR = os.path.join(ROOT, "sources")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 已登记的入口。新增来源必须在此登记，运行时不接受用户提供的任意 URL。
REGISTRY = {
    "prc-civil-code-2020": {
        "version": "2020-05-28",
        "title": "中华人民共和国民法典",
        "issuer": "全国人民代表大会",
        "source_type": "法律",
        "official_url": "https://www.gjxfj.gov.cn/2020-05/28/c_139952976.htm",
        "articles": ["第七百一十条", "第七百一十一条", "第七百一十四条"],
    },
    "housing-rental-regulation-2025": {
        "version": "2025-07-16",
        "title": "住房租赁条例（中华人民共和国国务院令第812号）",
        "issuer": "国务院",
        "source_type": "行政法规",
        "official_url": (
            "https://www.mee.gov.cn/zcwj/gwywj/202507/t20250722_1123995.shtml"
        ),
        "articles": ["第二条", "第十条"],
    },
}

SUSPICIOUS = re.compile(r"[\ufffd\u0000-\u0008\u200b]")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def http_get(url: str, timeout: int = 45) -> tuple[bytes, str]:
    """先按环境代理尝试，失败后直连重试一次。

    两次尝试都会如实记录；不静默替换为缓存或第三方镜像。
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last: Exception | None = None
    for opener in (
        urllib.request.build_opener(),  # 使用环境代理
        urllib.request.build_opener(urllib.request.ProxyHandler({})),  # 直连
    ):
        try:
            with opener.open(req, timeout=timeout) as resp:
                return resp.read(), (resp.headers.get("Content-Type") or "")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            continue
    raise RuntimeError(f"抓取失败：{last!r}")


def html_to_plain(raw: bytes) -> str:
    for enc in ("utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - 解码失败应中止而不是猜
        raise RuntimeError("无法解码页面，需人工核清编码")
    text = re.sub(r"(?is)<script.*?</script>", "", text)
    text = re.sub(r"(?is)<style.*?</style>", "", text)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", "\n", text))
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


def canonicalize(article_text: str) -> tuple[str, list[str]]:
    """空白规范化：仅折叠连续空白与去掉首尾空白，保留全部实词、否定与标点。"""
    warnings: list[str] = []
    if SUSPICIOUS.search(article_text):
        warnings.append("canonical_text 含替换字符或控制字符，需人工核清")
    text = re.sub(r"\s+", " ", article_text).strip()
    return text, warnings


ARTICLE_STOP = re.compile(r"第[一二三四五六七八九十百千零〇0-9]+条")


def split_articles(plain: str) -> dict[str, str]:
    """按‘第N条’切分正文。返回 {条号: 条文}。"""
    marks = [(m.start(), m.group(0)) for m in ARTICLE_STOP.finditer(plain)]
    out: dict[str, str] = {}
    for idx, (start, label) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(plain)
        body = plain[start + len(label) : end]
        # 同一条号可能在目录中重复出现，保留正文更长的一次
        if label not in out or len(body) > len(out[label]):
            out[label] = body
    return out


def provision_locator(label: str) -> str:
    return f"条={label}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="只处理指定 source_id")
    ap.add_argument("--reuse-raw", default=None, help="复用已下载的原始 HTML 目录")
    ap.add_argument(
        "--retrieved-at",
        default=None,
        help="ISO 8601；仅与 --reuse-raw 同用，记录该快照的实际取得时间",
    )
    ap.add_argument("--timeout", type=int, default=45)
    args = ap.parse_args()

    os.makedirs(SOURCES_DIR, exist_ok=True)
    if args.retrieved_at:
        retrieved_at = args.retrieved_at
    else:
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report: dict = {"retrieved_at": retrieved_at, "items": [], "warnings": []}

    for source_id, spec in REGISTRY.items():
        if args.only and source_id != args.only:
            continue
        sdir = os.path.join(SOURCES_DIR, source_id)
        raw_dir = os.path.join(sdir, "raw")
        canon_dir = os.path.join(sdir, "canonical")
        os.makedirs(raw_dir, exist_ok=True)
        os.makedirs(canon_dir, exist_ok=True)

        raw_path = os.path.join(raw_dir, f"{spec['version']}.html")
        reused = False
        if args.reuse_raw:
            cand = os.path.join(args.reuse_raw, source_id + ".html")
            if os.path.exists(cand):
                with open(cand, "rb") as fh:
                    raw = fh.read()
                reused = True
        if not reused:
            if os.path.exists(raw_path):
                with open(raw_path, "rb") as fh:
                    raw = fh.read()
                reused = True
            else:
                try:
                    raw, _ctype = http_get(spec["official_url"], args.timeout)
                except (urllib.error.URLError, TimeoutError) as exc:
                    report["warnings"].append(f"{source_id}: 抓取失败 {exc!r}")
                    print(f"[FAIL] {source_id}: {exc!r}", file=sys.stderr)
                    continue
        if not os.path.exists(raw_path):
            with open(raw_path, "wb") as fh:
                fh.write(raw)

        raw_sha = sha256_bytes(raw)
        plain = html_to_plain(raw)
        with open(os.path.join(sdir, "plain.txt"), "w", encoding="utf-8") as fh:
            fh.write(plain)

        articles = split_articles(plain)
        canonical: dict[str, dict] = {}
        warnings: list[str] = []
        for label in spec["articles"]:
            body = articles.get(label)
            if not body:
                warnings.append(f"{label}: 未在页面中定位到条文")
                continue
            text, w = canonicalize(body)
            warnings.extend(w)
            canon_path = os.path.join(canon_dir, f"{label}.txt")
            with open(canon_path, "w", encoding="utf-8") as fh:
                fh.write(text)
            canonical[label] = {
                "provision_locator": provision_locator(label),
                "canonical_text": text,
                "canonical_sha256": sha256_text(text),
            }
            print(f"[OK] {source_id} {label} len={len(text)}")

        meta = {
            "source_id": source_id,
            "version": spec["version"],
            "title": spec["title"],
            "issuer": spec["issuer"],
            "source_type": spec["source_type"],
            "official_url": spec["official_url"],
            "raw_snapshot": os.path.relpath(raw_path, ROOT),
            "raw_sha256": raw_sha,
            "raw_size_bytes": len(raw),
            "retrieved_at": retrieved_at,
            "raw_origin": "reused-snapshot" if reused else "live-retrieval",
            "articles": canonical,
            "warnings": warnings,
        }
        with open(os.path.join(sdir, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2, sort_keys=True)
        report["items"].append(
            {
                "source_id": source_id,
                "version": spec["version"],
                "raw_sha256": raw_sha,
                "articles": sorted(canonical.keys()),
                "warnings": warnings,
            }
        )

    out = os.path.join(ROOT, "evidence", "source-retrieval-report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
