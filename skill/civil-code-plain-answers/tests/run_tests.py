#!/usr/bin/env python3
"""测试执行器。

- 对话用例来自 tests/cases/basic.json；
- 代码级用例（T13 变体、T15、T16、T17、T22、T28、T30）在本文件内实现；
- 结果写入 evidence/<run>/case-results.jsonl 与 gate-results.json。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from core.datamodels import SessionSnapshot  # noqa: E402
from core.facts import SessionStore  # noqa: E402
from core.loader import ReferenceSet  # noqa: E402
from core.model_adapter import HeuristicAdapter, validate_plan  # noqa: E402
from core.pipeline import Pipeline  # noqa: E402

# 测试使用确定性后端：本机 Qwen 不可执行，模型参与的用例如实标为 NOT_RUN。
TEST_CONFIG = {"model_backend": "heuristic-no-model"}


def run_turns(refs, turns, attachments=None, cfg=None, session_id="test"):
    pipeline = Pipeline(refs, cfg or TEST_CONFIG)
    store = SessionStore(session_id=session_id)
    envelopes = []
    for idx, text in enumerate(turns):
        if text == "LONG_INPUT_WITH_EXCEPTION":
            text = "押金" + "合同里有一条例外：出租人未履行维修义务时除外。" * 220
        req = {
            "schema_version": "2.0",
            "request_id": f"req-{session_id}-{idx}",
            "session_id": session_id,
            "question": text,
            "attachments": (attachments or [[]] * len(turns))[idx] or [],
        }
        envelopes.append(pipeline.answer(req, store))
    return envelopes, store


def check_case(case, env, store, refs) -> list[str]:
    failures: list[str] = []
    exp = case.get("expect", {})
    text = env.get("text", "")

    if "outcome_in" in exp and env.get("outcome") not in exp["outcome_in"]:
        failures.append(f"outcome={env.get('outcome')} 不在 {exp['outcome_in']}")
    if "outcome_not_in" in exp and env.get("outcome") in exp["outcome_not_in"]:
        failures.append(f"outcome={env.get('outcome')} 命中禁止集合")
    if "runtime_status" in exp and env.get("runtime_status") != exp["runtime_status"]:
        failures.append(f"runtime_status={env.get('runtime_status')}")
    for code in exp.get("reason_codes_include", []):
        if code not in env.get("reason_codes", []):
            failures.append(f"缺少 reason_code {code}（实际 {env.get('reason_codes')}）")
    for s in exp.get("text_contains", []):
        if s not in text:
            failures.append(f"文本缺少：{s}")
    for s in exp.get("text_not_contains", []):
        if s in text:
            failures.append(f"文本不应包含：{s}")
    for pat in exp.get("text_regex_not_match", []):
        if re.search(pat, text):
            failures.append(f"文本命中禁用模式：{pat}")
    q = len(env.get("next_questions") or [])
    if q > exp.get("max_questions", 2):
        failures.append(f"追问 {q} 项超过上限 {exp['max_questions']}")
    if "min_text_len" in exp and len(text) < exp["min_text_len"]:
        failures.append(f"文本过短 {len(text)}")
    if "max_text_len" in exp and len(text) > exp["max_text_len"]:
        failures.append(f"文本过长 {len(text)} > {exp['max_text_len']}")
    if exp.get("citations_min") and len(env.get("citations") or []) < exp["citations_min"]:
        failures.append("引用数量不足")
    if exp.get("citations_max") is not None and len(env.get("citations") or []) > exp["citations_max"]:
        failures.append(f"引用数量 {len(env.get('citations'))} 超过 {exp['citations_max']}")
    for key, value in (exp.get("facts") or {}).items():
        rec = store.snapshot.facts.get(key)
        if rec is None or rec.value != value:
            failures.append(f"事实 {key} 期望 {value!r}，实际 {getattr(rec, 'value', None)!r}")
    for key in exp.get("facts_absent", []):
        rec = store.snapshot.facts.get(key)
        if rec is not None and rec.value is not None:
            failures.append(f"事实 {key} 不应被断言，实际 {rec.value!r}")
    if exp.get("no_legal_block"):
        kinds = {b["kind"] for b in env.get("blocks") or []}
        if "LEGAL_EXPLANATION" in kinds:
            failures.append("出现未开放的法律解释块")
    if exp.get("legal_still_disabled"):
        caps = {c["id"]: c["state"] for c in env.get("capability_results") or []}
        for cap in ("LEGAL01", "LEGAL02"):
            if caps.get(cap) not in (None, "NOT_ENABLED"):
                failures.append(f"{cap} 状态异常：{caps.get(cap)}")
    if exp.get("injection_detected"):
        if not (env.get("diagnostics") or {}).get("injection_hits"):
            failures.append("未记录资料注入命中")
    return failures


# ==================== 代码级用例 ====================
def code_cases(refs) -> list[dict]:
    out: list[dict] = []

    def record(case_id, gate_refs, ok, detail, note=""):
        out.append(
            {
                "case_id": case_id,
                "gate_refs": gate_refs,
                "result": "PASS" if ok else "FAIL",
                "detail": detail,
                "note": note,
            }
        )

    # T13-01 条号错误：把条文定位改掉，来源解析必须失败
    tmp = tempfile.mkdtemp()
    try:
        dst = os.path.join(tmp, "references")
        shutil.copytree(os.path.join(ROOT, "references"), dst)
        src_path = os.path.join(dst, "sources.json")
        doc = json.load(open(src_path, encoding="utf-8"))
        for s in doc["sources"]:
            if s["source_id"] == "prc-civil-code-2020":
                for a in s["articles"]:
                    if a["provision_locator"] == "条=第七百一十条":
                        a["provision_locator"] = "条=第七百九十九条"
        json.dump(doc, open(src_path, "w", encoding="utf-8"), ensure_ascii=False)
        bad = ReferenceSet(dst)
        env, _ = run_turns(bad, ["有没有相关法条？房东扣了 500 元"])
        has_710 = "第七百一十条" in env[-1]["text"]
        record("T13-01", ["G01", "G07"], not has_710,
               "条号被改后不再输出第七百一十条" if not has_710 else "仍然输出了被改动的条号")

        # T13-03 摘要不符：直接测试 renderer 拒绝摘要不符的来源
        from core.renderer import Renderer
        test_refs = ReferenceSet(dst)
        # 把 711 的规范文本改掉，同时保留模板中的旧 sha256
        for s in test_refs.sources["prc-civil-code-2020"]["articles"]:
            if s["provision_locator"] == "条=第七百一十一条":
                s["canonical_text"] = s["canonical_text"].replace("损失", "损耗")
        try:
            Renderer(test_refs)._bind(
                "canonical_text",
                {"type": "text", "source_kind": "source_article",
                 "provision_locator": "条=第七百一十一条", "required": True},
                test_refs.templates["T_SOURCE_CIVIL_711"],
                None, {},
            )
            tampered = False
        except Exception:  # noqa: BLE001
            tampered = True
        record("T13-03", ["G01", "G05"], tampered,
               "renderer 拒绝摘要不符的来源" if tampered else "未拒绝篡改来源",
               "引用摘要与来源记录分离；摘要不符时该条不可引用")

        # T30 规则停用：把 RENT01_NAV 置为 DISABLED
        rules_path = os.path.join(dst, "rules.json")
        rdoc = json.load(open(rules_path, encoding="utf-8"))
        for r in rdoc["rules"]:
            if r["rule_id"] == "RENT01_NAV":
                r["lifecycle_state"] = "DISABLED"
        json.dump(rdoc, open(rules_path, "w", encoding="utf-8"), ensure_ascii=False)
        bad3 = ReferenceSet(dst)
        env3, _ = run_turns(bad3, ["押金没退，我该先看什么？"])
        caps = {c["id"]: c["state"] for c in env3[-1]["capability_results"]}
        record("T30", ["G02", "G04", "G12"], caps.get("NAV01") == "NOT_ENABLED",
               f"停用后 NAV01={caps.get('NAV01')}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # T15 草稿规则未审核：即使强制 ACTIVE，校验也必须拦下法律表达
    tmp2 = tempfile.mkdtemp()
    try:
        dst = os.path.join(tmp2, "references")
        shutil.copytree(os.path.join(ROOT, "references"), dst)
        rpath = os.path.join(dst, "rules.json")
        rdoc = json.load(open(rpath, encoding="utf-8"))
        for r in rdoc["rules"]:
            if r["rule_id"] == "RENT02_LEGAL":
                r["lifecycle_state"] = "ACTIVE"
        json.dump(rdoc, open(rpath, "w", encoding="utf-8"), ensure_ascii=False)
        # 同时把 LEGAL01 塞进启用清单，模拟「绕过审核强行开放」
        mpath = os.path.join(dst, "release-manifest.json")
        mdoc = json.load(open(mpath, encoding="utf-8"))
        mdoc["enabled_capabilities"] = sorted(set(mdoc["enabled_capabilities"]) | {"LEGAL01"})
        json.dump(mdoc, open(mpath, "w", encoding="utf-8"), ensure_ascii=False)
        forced = ReferenceSet(dst)
        env, _ = run_turns(forced, ["墙上有印子，是不是正常损耗？"])
        kinds = {b["kind"] for b in env[-1]["blocks"]}
        record("T15", ["G02", "G04"],
               "LEGAL_EXPLANATION" not in kinds
               and env[-1]["runtime_status"] == "CHECK_FAILED",
               f"强行开放后 blocks={sorted(kinds)} status={env[-1]['runtime_status']}",
               "缺少真实复核绑定时，校验拦截并保留失败状态")
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)

    # T16-01 连接失败
    cfg = {"model_backend": "ollama", "ollama": {"host": "http://127.0.0.1:9", "model": "x"}}
    env, _ = run_turns(refs, ["押金没退"], cfg=cfg)
    ok = env[-1]["outcome"] == "UNAVAILABLE" and "MODEL_UNAVAILABLE" in env[-1]["reason_codes"]
    record("T16-01", ["G07", "G10"], ok, f"reason={env[-1]['reason_codes']}")

    # T16-02 超时：用本地「接受连接但迟迟不返回」的受控服务，确定性触发读取超时。
    # 受控替身仅用于故障注入；此处只验证超时分类，不代表真实模型可用。
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(0.2)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def _slow_server():
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except (socket.timeout, OSError):
                continue
            try:
                conn.recv(65536)
                time.sleep(1.5)  # 不返回响应，迫使客户端读取超时
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    worker = threading.Thread(target=_slow_server, daemon=True)
    worker.start()
    try:
        cfg = {"model_backend": "ollama",
               "ollama": {"host": f"http://127.0.0.1:{port}", "model": "x",
                          "connect_timeout_s": 1.0, "read_timeout_s": 0.3}}
        env, _ = run_turns(refs, ["押金没退"], cfg=cfg)
        ok = "MODEL_TIMEOUT" in env[-1]["reason_codes"]
        record("T16-02", ["G07", "G10"], ok, f"reason={env[-1]['reason_codes']}",
               "受控慢响应服务触发读取超时；仅验证超时分类，不代表真实模型可用")
    finally:
        stop.set()
        srv.close()

    # T16-03 非法 CandidatePlan
    bad_plans = [
        {"commands": ["rm -rf /"]},
        {"fact_updates": [{"key": "not_a_key", "value": 1, "state": "ASSERTED"}]},
        {"candidate_template_ids": ["T_DOES_NOT_EXIST"]},
        {"fact_updates": [{"key": "keys_returned", "state": "PROVEN", "value": True}]},
        "not-a-dict",
    ]
    rejected = 0
    for p in bad_plans:
        try:
            validate_plan(p, refs)
        except Exception:  # noqa: BLE001
            rejected += 1
    # 未登记的事实键应被丢弃而不是写入；这一条不算拒收，单独验证
    dropped = validate_plan(
        {"fact_updates": [{"key": "not_a_key", "value": 1, "state": "ASSERTED"}]}, refs
    )
    record("T16-03", ["G07"], rejected == len(bad_plans) - 1 and dropped["fact_updates"] == [],
           f"{rejected}/{len(bad_plans) - 1} 个非法候选被拒收；未登记键被丢弃")

    # T17 宿主输出约束
    env, _ = run_turns(refs, ["押金没退"])
    rc = env[-1]["render_contract"]
    record("T17", ["G06"], rc.get("allow_host_append") is False and bool(rc.get("text_sha256")),
           f"allow_host_append={rc.get('allow_host_append')}")

    # T28 幂等与冲突
    pipeline = Pipeline(refs, TEST_CONFIG)
    store = SessionStore(session_id="idem")
    req = {"schema_version": "2.0", "request_id": "same-id", "session_id": "idem",
           "question": "押金没退，钥匙交了", "attachments": []}
    pipeline.answer(req, store)
    first = store.snapshot.facts.get("keys_returned")
    pipeline2 = Pipeline(refs, TEST_CONFIG)
    env2 = pipeline2.answer(req, store)
    again = store.snapshot.facts.get("keys_returned")
    req2 = dict(req, question="完全不同的输入")
    env3 = Pipeline(refs, TEST_CONFIG).answer(req2, store)
    ok = (first is not None and again is not None
          and first.fact_id == again.fact_id
          and "REQUEST_CONFLICT" in env3["reason_codes"])
    record("T28", ["G03", "G06"], ok,
           f"同 ID 未重复写入；不同输入 reason={env3['reason_codes']}")

    # MODEL 依赖：本机 Qwen 不可执行，真实模型用例保持 NOT_RUN
    out.append(
        {
            "case_id": "T22",
            "gate_refs": ["G03", "G04", "G05", "G06", "G07"],
            "result": "NOT_RUN",
            "detail": "需要真实本地模型回放；本机模型条目为 remote 代理且上游不可达",
            "note": "已在确定性后端上重复两轮基础用例（见 repeat 记录）",
        }
    )
    return out


def main() -> int:
    started = datetime.now(timezone.utc)
    refs = ReferenceSet()
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = os.path.join(ROOT, "evidence", f"run-{run_id}")
    os.makedirs(evidence_dir, exist_ok=True)

    cases = json.load(open(os.path.join(HERE, "cases", "basic.json"), encoding="utf-8"))
    results: list[dict] = []

    for case in cases["cases"]:
        turns = case["turns"]
        attachments = case.get("attachments")
        t0 = time.time()
        try:
            envelopes, store = run_turns(refs, turns, attachments)
            env = envelopes[-1]
            failures = check_case(case, env, store, refs)
        except Exception as exc:  # noqa: BLE001
            failures = [f"执行异常：{exc!r}"]
            env, store, envelopes = {}, None, []
        if not failures and case.get("second_session"):
            sub = case["second_session"]
            env2, store2 = run_turns(refs, sub["turns"], session_id="second-session")
            failures += [f"[新会话] {f}" for f in check_case(sub, env2[-1], store2, refs)]
        results.append(
            {
                "case_id": case["case_id"],
                "gate_refs": case.get("gate_refs", []),
                "result": "PASS" if not failures else "FAIL",
                "failure_reasons": failures,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "outcome": env.get("outcome"),
                "runtime_status": env.get("runtime_status"),
                "reason_codes": env.get("reason_codes"),
                "text_len": len(env.get("text", "")),
                "text_preview": (env.get("text", "") or "")[:200],
                "citations": len(env.get("citations") or []),
            }
        )

    # 重复一轮基础用例作为回归稳定性检查（确定性后端）
    repeat_failures = 0
    for case in cases["cases"]:
        try:
            envelopes, store = run_turns(refs, case["turns"], case.get("attachments"))
            if check_case(case, envelopes[-1], store, refs):
                repeat_failures += 1
        except Exception:  # noqa: BLE001
            repeat_failures += 1
    results.append(
        {
            "case_id": "T22-repeat",
            "gate_refs": ["G03", "G04", "G05"],
            "result": "PASS" if repeat_failures == 0 else "FAIL",
            "failure_reasons": [] if repeat_failures == 0 else [f"{repeat_failures} 个用例重跑不一致"],
            "note": "确定性后端重复执行基础用例；不含真实模型",
        }
    )

    results += code_cases(refs)

    with open(os.path.join(evidence_dir, "case-results.jsonl"), "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    passed = sum(1 for r in results if r["result"] == "PASS")
    failed = sum(1 for r in results if r["result"] == "FAIL")
    notrun = sum(1 for r in results if r["result"] == "NOT_RUN")
    summary = {
        "run_id": run_id,
        "started_at": started.isoformat(timespec="seconds"),
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "not_run": notrun,
        "backend": "heuristic-no-model（本机 Qwen 不可执行）",
    }
    json.dump(summary, open(os.path.join(evidence_dir, "test-summary.json"), "w",
                            encoding="utf-8"), ensure_ascii=False, indent=2, sort_keys=True)

    for r in results:
        flag = {"PASS": "PASS", "FAIL": "FAIL", "NOT_RUN": "SKIP"}[r["result"]]
        print(f"[{flag}] {r['case_id']} {r.get('failure_reasons') or r.get('detail','')}")
    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
