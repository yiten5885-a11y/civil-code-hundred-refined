"""受控完整流程（编排）。

规格 4.2、4.3、6.3、9：
- 输入检查与安全分流先执行；
- 同一轮固定版本快照；
- 模型只给候选，程序决定获准内容；
- 失败时最多一次受限修复；达到截止时间使用备用答复；
- 宿主最终文字纳入验收。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from . import hashing, input_guard
from .datamodels import SEMANTIC, SessionSnapshot
from .facts import SessionStore
from .loader import ReferenceSet
from .model_adapter import (
    HeuristicAdapter,
    ModelOutputInvalid,
    ModelTimeout,
    ModelUnavailable,
    OllamaAdapter,
    validate_plan,
)
from .policy import PolicyEngine
from .predicates import FactStore
from .renderer import Renderer
from .rules import RuleResolver
from .validator import FinalValidator

DEFAULT_CONFIG: dict[str, Any] = {
    "model_backend": "auto",
    "ollama": {
        "host": "http://127.0.0.1:11434",
        "model": "",
        "connect_timeout_s": 3,
        "read_timeout_s": 60,
        "temperature": 0.1,
    },
    "limits": {
        "total_deadline_s": 120,
        "max_repair": 1,
        "max_questions": 2,
    },
}

FALLBACK_TEMPLATES = {
    "MODEL_OUTPUT_INVALID": ["T_NAV_DEPOSIT_START", "T_ACT_FIND_CLAUSE", "T_LIMIT_NO_LEGAL_CONCLUSION"],
    "MODEL_TIMEOUT": ["T_MODEL_TIMEOUT", "T_NAV_DEPOSIT_START"],
    "INTERNAL_ERROR": ["T_ERROR_TECH"],
    "CHECK_FAILED": ["T_NAV_DEPOSIT_START", "T_LIMIT_NO_LEGAL_CONCLUSION"],
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Pipeline:
    def __init__(self, refs: ReferenceSet, config: dict | None = None):
        self.refs = refs
        self.cfg = _merge(DEFAULT_CONFIG, config or {})
        self.resolver = RuleResolver(refs.rules, refs.templates)
        self.policy = PolicyEngine(refs, self.resolver, refs.manifest)
        self.renderer = Renderer(refs)
        self.validator = FinalValidator(refs)
        self.diagnostics: dict[str, Any] = {"notes": [], "injection_hits": []}

    # ==================== 主入口 ====================
    def answer(self, request: dict, store: SessionStore) -> dict:
        started = time.time()
        deadline = float(self.cfg["limits"]["total_deadline_s"])
        request_id = request.get("request_id") or str(uuid.uuid4())
        turn_id = str(uuid.uuid4())
        message = request.get("question") or ""
        attachments = request.get("attachments") or []

        guard = input_guard.analyze(message, attachments)
        signals = guard["signals"]
        self.diagnostics["injection_hits"] = guard["injection_hits"]
        model_calls = 0

        # 1. 长度
        ok_len, chars = input_guard.check_length(message)
        if not ok_len:
            return self._fallback(
                request_id, store, "CONTEXT_TOO_LARGE", ["T_CONTEXT_TOO_LARGE"],
                started, model_calls, signals,
            )

        # 2. 安全分流：不等待模型、不等待来源检索
        if signals.get("safety_now"):
            rendered = self.renderer.render(["T_SAFETY_NOW"], self._store(store), signals)
            return self._envelope(
                request_id, store, rendered, [], "SAFETY", "OK",
                ["SAFETY"], {}, started, model_calls, signals, [],
            )

        # 3. 请求幂等 / 冲突：在场景判定之前处理，避免被后续分支掩盖
        before_rev = store.snapshot.revision
        input_sha = hashing.sha256_text(message)
        seen = next(
            (h for h in store.snapshot.history if h.get("request_id") == request_id), None
        )
        if seen is not None and seen.get("input_sha") != input_sha:
            return self._fallback(
                request_id, store, "REQUEST_CONFLICT", ["T_ERROR_TECH"],
                started, model_calls, signals,
            )
        if seen is None:
            store.snapshot.history.append(
                {"request_id": request_id, "input_sha": input_sha, "revision": before_rev}
            )
        else:
            self.diagnostics["notes"].append(
                f"request_id={request_id} 已处理过，本轮不重复应用事实"
            )

        # 4. 场景判定（会话已确立的场景不因单条消息缺关键词而丢失）
        scenario_id = self._scenario(request, message) or store.snapshot.scenario_id or None
        if scenario_id is None:
            rendered = self.renderer.render(
                ["T_OUT_OF_SCOPE_GENERIC"], self._store(store), signals
            )
            return self._envelope(
                request_id, store, rendered, [], "OUT_OF_SCOPE", "OK",
                ["OUT_OF_SCOPE"], {}, started, model_calls, signals, [],
            )

        # 4. 模型候选（带截止与一次受限修复）
        store_fs = self._store(store, signals)
        fact_store = FactStore(store.snapshot, signals)
        attempts = []
        plan = None
        backend_used = None
        remaining = deadline - (time.time() - started)
        if remaining <= 1:
            return self._fallback(
                request_id, store, "MODEL_TIMEOUT", FALLBACK_TEMPLATES["MODEL_TIMEOUT"],
                started, model_calls, signals,
            )

        adapter_info = self._select_adapter()
        backend_used = adapter_info["backend"]
        # 只有 auto 允许降级到启发式路径；显式指定 ollama 时如实报不可用
        allow_degrade = self.cfg.get("model_backend", "auto") == "auto"
        max_repair = int(self.cfg["limits"]["max_repair"])
        for attempt in range(max_repair + 1):
            try:
                raw = adapter_info["adapter"].propose(
                    message,
                    {
                        "templates": sorted(self.refs.templates),
                        "rules": sorted(self.refs.rules),
                    },
                )
                model_calls += 1
                plan = validate_plan(raw["plan"], self.refs)
                attempts.append(
                    {"attempt": attempt, "result": "VALID", "elapsed_ms": raw.get("elapsed_ms")}
                )
                break
            except (ModelOutputInvalid,) as exc:
                attempts.append({"attempt": attempt, "result": "INVALID", "error": str(exc)})
                if attempt >= max_repair:
                    return self._fallback(
                        request_id, store, "MODEL_OUTPUT_INVALID",
                        FALLBACK_TEMPLATES["MODEL_OUTPUT_INVALID"],
                        started, model_calls, signals,
                    )
            except ModelTimeout:
                attempts.append({"attempt": attempt, "result": "TIMEOUT"})
                return self._fallback(
                    request_id, store, "MODEL_TIMEOUT", FALLBACK_TEMPLATES["MODEL_TIMEOUT"],
                    started, model_calls, signals,
                )
            except ModelUnavailable as exc:
                attempts.append({"attempt": attempt, "result": "UNAVAILABLE", "error": str(exc)})
                if adapter_info["backend"] == "ollama" and allow_degrade:
                    # 显式降级到启发式路径，并如实记录
                    adapter_info = {"backend": "heuristic-no-model", "adapter": HeuristicAdapter()}
                    backend_used = "heuristic-no-model"
                    self.diagnostics["notes"].append(f"模型不可用，已降级：{exc}")
                    continue
                return self._fallback(
                    request_id, store, "MODEL_UNAVAILABLE",
                    ["T_MODEL_UNAVAILABLE", "T_NAV_DEPOSIT_START", "T_LIMIT_NO_LEGAL_CONCLUSION"],
                    started, model_calls, signals,
                )
        if plan is None:
            return self._fallback(
                request_id, store, "MODEL_UNAVAILABLE",
                ["T_MODEL_UNAVAILABLE", "T_NAV_DEPOSIT_START", "T_LIMIT_NO_LEGAL_CONCLUSION"],
                started, model_calls, signals,
            )

        if backend_used == "heuristic-no-model":
            self.diagnostics["notes"].append("本轮使用启发式降级路径，未调用本地模型")
        store.snapshot.scenario_id = scenario_id

        # 5. 事实更新（首次执行；已处理过的 request_id 不重复应用）
        if seen is None:
            store.apply_updates(
                plan["fact_updates"], message, turn_id,
                speaker="user", evidence_level="USER_STATEMENT",
            )
            self._apply_conflicts(message, store, turn_id)
            self._apply_attachment_facts(attachments, store, turn_id)
            store.bump()
        fact_store = FactStore(store.snapshot, signals)

        # 6. 策略与渲染
        plan_out = self.policy.plan(scenario_id, fact_store, signals)
        selected = list(plan_out["selected_templates"])
        questions = list(plan_out["question_templates"])
        if backend_used == "heuristic-no-model" and "T_MODEL_UNAVAILABLE" not in selected:
            selected.append("T_MODEL_UNAVAILABLE")
        rendered = self.renderer.render(selected + questions, fact_store, signals)

        for b in rendered["blocks"]:
            if b["kind"] == "QUESTION":
                continue
            b["rule_refs"] = plan_out["template_rule_map"].get(b["template_id"], [])
        q_texts = {
            b["template_id"]: b["text"] for b in rendered["blocks"] if b["kind"] == "QUESTION"
        }

        # 7. 校验
        result = self.validator.validate(
            [b for b in rendered["blocks"] if b["kind"] != "QUESTION"],
            questions,
            rendered["citations"],
            plan_out["rules_in_play"],
            plan_out["traces"],
        )
        runtime_status = "OK"
        reason_codes = list(plan_out["reason_codes"])
        if result["status"] == "FAIL":
            runtime_status = "CHECK_FAILED"
            reason_codes.append("CHECK_FAILED")
        if not result["blocks"]:
            return self._fallback(
                request_id, store, "CHECK_FAILED", FALLBACK_TEMPLATES["CHECK_FAILED"],
                started, model_calls, signals,
            )

        # 8. 追问落库 + 文本组装
        text = self.renderer._assemble(result["blocks"] + [
            b for b in rendered["blocks"]
            if b["kind"] == "QUESTION" and b["template_id"] in questions
        ])
        for tid in questions:
            store.snapshot.asked_questions.append(
                {"template_id": tid, "revision": store.snapshot.revision}
            )

        capability_results = self._merge_capabilities(plan_out["capability_results"])
        outcome = self._outcome(result["blocks"], questions, capability_results)

        self.diagnostics.update(
            {
                "model_attempts": attempts,
                "scenario_id": scenario_id,
                "template_ids": [b["template_id"] for b in result["blocks"]] + questions,
                "fact_diff": store.diff(before_rev),
                "traces": plan_out["traces"],
                "removed": result["removed"],
                "skipped": rendered.get("skipped"),
                "input_chars": chars,
            }
        )

        return self._envelope(
            request_id, store,
            {"blocks": result["blocks"], "text": text, "citations": rendered["citations"]},
            questions, outcome, runtime_status, reason_codes, capability_results,
            started, model_calls, signals,
            [q_texts.get(q, "") for q in questions],
            validation=result,
            backend=backend_used,
        )

    # ==================== 内部 ====================
    def _store(self, store: SessionStore, signals: dict | None = None) -> FactStore:
        return FactStore(store.snapshot, signals or {})

    def _select_adapter(self) -> dict:
        backend = self.cfg.get("model_backend", "auto")
        ollama_cfg = self.cfg.get("ollama", {})
        if backend in ("ollama", "auto"):
            model = ollama_cfg.get("model") or ""
            if model:
                return {
                    "backend": "ollama",
                    "adapter": OllamaAdapter(
                        ollama_cfg.get("host", "http://127.0.0.1:11434"),
                        model,
                        float(ollama_cfg.get("connect_timeout_s", 3)),
                        float(ollama_cfg.get("read_timeout_s", 60)),
                        float(ollama_cfg.get("temperature", 0.1)),
                    ),
                }
            if backend == "ollama":
                return {
                    "backend": "ollama",
                    "adapter": _MissingModelAdapter("未配置 ollama.model"),
                }
        return {"backend": "heuristic-no-model", "adapter": HeuristicAdapter()}

    def _scenario(self, request: dict, message: str) -> str | None:
        import re

        from .model_adapter import SCENARIO_PATTERNS

        hint = request.get("scenario_hint") or request.get("scenario")
        if hint == "rent_deposit":
            return "rent_deposit"
        if re.search(SCENARIO_PATTERNS, message or ""):
            return "rent_deposit"
        return None

    def _apply_conflicts(self, message: str, store: SessionStore, turn_id: str) -> None:
        import re

        from .model_adapter import CONFLICT_HINT

        if not re.search(CONFLICT_HINT, message or ""):
            return
        for key in ("keys_returned", "handover_record_signed", "occupancy_moved_out"):
            if key in store.snapshot.facts and store.snapshot.facts[key].state == "ASSERTED":
                store.apply_updates(
                    [{"key": key, "state": "CONFLICT", "source_quote": message[:60]}],
                    message, turn_id,
                )

    def _apply_attachment_facts(self, attachments: list, store: SessionStore, turn_id: str) -> None:
        """附件只登记「有图片」这一事实，不声称看过或核验过图片内容。"""
        has_image = any(
            isinstance(a, dict) and str(a.get("kind", "")).lower() in ("image", "photo", "图片")
            for a in attachments or []
        )
        if not has_image:
            return
        store.apply_updates(
            [{"key": "image_attachment", "value": True, "state": "ASSERTED",
              "source_quote": ""}],
            "", turn_id, evidence_level="USER_STATEMENT",
        )

    def _merge_capabilities(self, results: list[dict]) -> list[dict]:
        """同一能力取最差状态，便于对外展示。"""
        order = ["DELIVERED", "NEEDS_FACTS", "OUT_OF_SCOPE", "SOURCE_UNAVAILABLE",
                 "NOT_ENABLED", "ERROR"]
        best: dict[str, str] = {}
        for r in results:
            cur = best.get(r["id"])
            if cur is None or order.index(r["state"]) > order.index(cur):
                best[r["id"]] = r["state"]
        return [{"id": k, "state": v} for k, v in sorted(best.items())]

    def _outcome(self, blocks: list[dict], questions: list[str], caps: list[dict]) -> str:
        if not blocks and not questions:
            return "UNAVAILABLE"
        if questions and blocks:
            return "NEEDS_INPUT"
        if blocks:
            return "ANSWERED"
        return "NEEDS_INPUT"

    def _fallback(self, request_id, store, reason_code, template_ids, started,
                  model_calls, signals, questions=None) -> dict:
        rendered = self.renderer.render(template_ids, self._store(store, signals), signals)
        caps = [{"id": c, "state": "NOT_ENABLED"} for c in ("NAV01", "NAV02", "NAV03")]
        return self._envelope(
            request_id, store, rendered, questions or [], "UNAVAILABLE", "OK",
            [reason_code], caps, started, model_calls, signals, [],
        )

    def _envelope(self, request_id, store, rendered, questions, outcome, runtime_status,
                  reason_codes, capability_results, started, model_calls, signals,
                  question_texts, validation=None, backend=None) -> dict:
        text = rendered["text"]
        blocks = rendered["blocks"]
        elapsed = int((time.time() - started) * 1000)
        return {
            "schema_version": "2.0",
            "request_id": request_id,
            "runtime_status": runtime_status,
            "outcome": outcome,
            "capability_results": capability_results,
            "reason_codes": reason_codes,
            "blocks": blocks,
            "text": text,
            "citations": rendered["citations"],
            "next_questions": question_texts,
            "validation": {
                "status": (validation or {}).get("status", "NOT_RUN"),
                "checks": (validation or {}).get("checks", []),
                "removed": (validation or {}).get("removed", []),
                "text_sha256": hashing.sha256_text(text),
            },
            "render_contract": {
                "text_sha256": hashing.sha256_text(text),
                "renderer": "deterministic-template-v1",
                "allow_host_append": False,
            },
            "session_revision": store.snapshot.revision,
            "release_id": (self.refs.manifest or {}).get("release_id"),
            "timing": {"elapsed_ms": elapsed},
            "model_calls": model_calls,
            "model_backend": backend,
            "signals": signals,
            "diagnostics": self.diagnostics,
            "legacy": {
                "status": outcome,
                "exit_code": 3 if runtime_status == "CHECK_FAILED" else (
                    2 if runtime_status == "ERROR" else 0
                ),
            },
        }


class _MissingModelAdapter:
    def __init__(self, reason: str):
        self.reason = reason

    def propose(self, message, context):  # pragma: no cover
        raise ModelUnavailable(self.reason)
