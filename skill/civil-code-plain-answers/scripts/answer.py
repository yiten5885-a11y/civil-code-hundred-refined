#!/usr/bin/env python3
"""唯一入口 answer.py。

用法：
    python3 answer.py --question "押金还没退，我该先看什么？"
    python3 answer.py --request request.json [--session-file s.json] [--diag]
    cat request.json | python3 answer.py

输出：stdout 只输出约定 JSON；诊断与错误进 stderr。
退出码：0 正常结束（含适当的有限答复）；2 请求或运行故障；3 输出校验失败。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.facts import SessionStore  # noqa: E402
from core.loader import ReferenceSet, PACKAGE_ROOT  # noqa: E402
from core.pipeline import Pipeline  # noqa: E402

CONFIG_EXAMPLE = os.path.join(PACKAGE_ROOT, "config", "example.json")
CONFIG_LOCAL = os.path.join(PACKAGE_ROOT, "config", "local.json")


def load_config(path: str | None) -> dict:
    candidates = [path] if path else [CONFIG_LOCAL, CONFIG_EXAMPLE]
    for cand in candidates:
        if cand and os.path.exists(cand):
            with open(cand, "r", encoding="utf-8") as fh:
                return json.load(fh)
    return {}


def build_request(args: argparse.Namespace, raw: dict | None) -> dict:
    if raw:
        req = dict(raw)
    else:
        req = {"question": args.question or ""}
        if args.scenario:
            req["scenario_hint"] = args.scenario
    req.setdefault("request_id", str(uuid.uuid4()))
    req.setdefault("session_id", args.session_id or "cli-session")
    req.setdefault("attachments", [])
    return req


def load_session(path: str | None, request: dict) -> SessionStore:
    from core.datamodels import SessionSnapshot

    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            snap = SessionSnapshot.from_dict(json.load(fh))
        return SessionStore(snap)
    return SessionStore(session_id=request.get("session_id") or "cli-session")


def save_session(path: str | None, store: SessionStore) -> None:
    if not path:
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(store.snapshot.to_dict(), fh, ensure_ascii=False, indent=2, sort_keys=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="民法典·百炼白话问答（受控入口）")
    ap.add_argument("--question", help="用户问题（v1 简写）")
    ap.add_argument("--scenario", help="场景提示，仅作候选，不覆盖用户真实范围")
    ap.add_argument("--request", help="v2 请求 JSON 文件路径；缺省从 stdin 读取")
    ap.add_argument("--session-id", help="会话标识；与 --session-file 同用时以文件为准")
    ap.add_argument("--config", help="配置文件路径；缺省 config/local.json 再 config/example.json")
    ap.add_argument("--session-file", help="会话持久化文件；缺省仅内存，进程退出即丢弃")
    ap.add_argument("--diag", help="诊断输出文件路径；缺省仅 stderr 摘要")
    args = ap.parse_args()

    raw = None
    if args.request:
        with open(args.request, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    elif not sys.stdin.isatty():
        data = sys.stdin.read().strip()
        if data:
            try:
                raw = json.loads(data)
            except json.JSONDecodeError:
                print("输入不是合法 JSON", file=sys.stderr)
                return 2
    if raw is None and not args.question:
        print("缺少 --question 或请求 JSON", file=sys.stderr)
        return 2

    request = build_request(args, raw)
    try:
        refs = ReferenceSet()
    except Exception as exc:  # noqa: BLE001
        print(f"参考数据加载失败：{exc!r}", file=sys.stderr)
        return 2
    if refs.integrity_errors:
        for err in refs.integrity_errors:
            print(f"[完整性] {err}", file=sys.stderr)

    cfg = load_config(args.config)
    store = load_session(args.session_file, request)

    try:
        pipeline = Pipeline(refs, cfg)
        envelope = pipeline.answer(request, store)
    except Exception as exc:  # noqa: BLE001
        print(f"[运行故障] {exc!r}", file=sys.stderr)
        envelope = {
            "schema_version": "2.0",
            "request_id": request.get("request_id"),
            "runtime_status": "ERROR",
            "outcome": "UNAVAILABLE",
            "reason_codes": ["INTERNAL_ERROR"],
            "text": "处理这一步时出了技术故障，本轮没有完成。可以稍后再试一次。",
            "blocks": [],
            "citations": [],
            "next_questions": [],
            "validation": {"status": "NOT_RUN"},
            "session_revision": store.snapshot.revision,
            "legacy": {"status": "SYSTEM_ERROR", "exit_code": 2},
        }

    save_session(args.session_file, store)

    print(json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True))
    if args.diag:
        with open(args.diag, "w", encoding="utf-8") as fh:
            json.dump(envelope.get("diagnostics", {}), fh, ensure_ascii=False, indent=2)
    else:
        notes = envelope.get("diagnostics", {}).get("notes") or []
        for note in notes:
            print(f"[诊断] {note}", file=sys.stderr)

    return int(envelope.get("legacy", {}).get("exit_code", 0))


if __name__ == "__main__":
    raise SystemExit(main())
