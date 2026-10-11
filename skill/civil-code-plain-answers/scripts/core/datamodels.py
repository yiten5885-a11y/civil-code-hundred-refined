"""逻辑数据结构。

对应规格第五部分。这里是内存中的数据结构，持久化为 JSON 文件；
不要求每个对象独立服务。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, asdict
from typing import Any

SCHEMA_VERSION = "2.0"

# ---- 三值 ----
TRUE = "TRUE"
FALSE = "FALSE"
UNKNOWN = "UNKNOWN"


# ---- 事实状态 ----
ASSERTED = "ASSERTED"
UNKNOWN_STATE = "UNKNOWN"
CONFLICT = "CONFLICT"
RETRACTED = "RETRACTED"

# ---- 证据等级 ----
USER_STATEMENT = "USER_STATEMENT"
DOCUMENT_EXCERPT = "DOCUMENT_EXCERPT"

# ---- 摘要种类 ----
FILE_BYTES = "FILE_BYTES"
CANONICAL_TEXT = "CANONICAL_TEXT"
SEMANTIC = "SEMANTIC"


@dataclass
class FactRecord:
    fact_id: str
    key: str
    value: Any = None
    state: str = ASSERTED
    speaker: str = "user"
    evidence_level: str = USER_STATEMENT
    turn_id: str = ""
    source_quote: str = ""
    source_span: dict | None = None
    supersedes: list[str] = field(default_factory=list)
    created_at: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SessionSnapshot:
    session_id: str
    scenario_id: str = ""  # 会话已确立的场景；多轮时不因单条消息缺关键词而丢失
    revision: int = 0
    facts: dict[str, FactRecord] = field(default_factory=dict)
    conflict_groups: list[dict] = field(default_factory=list)
    asked_questions: list[str] = field(default_factory=list)
    rule_versions: dict[str, str] = field(default_factory=dict)
    invalidated_advice: list[str] = field(default_factory=list)
    updated_at: str = ""
    history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "scenario_id": self.scenario_id,
            "revision": self.revision,
            "facts": {k: v.to_dict() for k, v in self.facts.items()},
            "conflict_groups": copy.deepcopy(self.conflict_groups),
            "asked_questions": list(self.asked_questions),
            "rule_versions": dict(self.rule_versions),
            "invalidated_advice": list(self.invalidated_advice),
            "updated_at": self.updated_at,
            "history": copy.deepcopy(self.history),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionSnapshot":
        snap = cls(
            session_id=data.get("session_id", ""),
            scenario_id=data.get("scenario_id", ""),
            revision=int(data.get("revision", 0)),
            updated_at=data.get("updated_at", ""),
        )
        for key, raw in (data.get("facts") or {}).items():
            snap.facts[key] = FactRecord(**raw)
        snap.conflict_groups = list(data.get("conflict_groups") or [])
        snap.asked_questions = list(data.get("asked_questions") or [])
        snap.rule_versions = dict(data.get("rule_versions") or {})
        snap.invalidated_advice = list(data.get("invalidated_advice") or [])
        snap.history = list(data.get("history") or [])
        return snap


def ref(obj_id: str, version: str, sha: str, kind: str = SEMANTIC) -> dict:
    """统一的带版本引用。禁止仅凭 ID 自动换用最新版本。"""
    return {"id": obj_id, "version": version, "sha256": sha, "hash_kind": kind}
