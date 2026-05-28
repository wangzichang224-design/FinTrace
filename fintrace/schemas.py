from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal, TypedDict


class Decision(str, Enum):
    APPROVE = "APPROVE"
    APPROVE_WITH_FLEX = "APPROVE_WITH_FLEX"
    REJECT = "REJECT"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    ESCALATE_FRAUD = "ESCALATE_FRAUD"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TraceStatus(str, Enum):
    OK = "OK"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass
class TraceEvent:
    node_name: str
    input_refs: list[str] = field(default_factory=list)
    output_refs: list[str] = field(default_factory=list)
    status: str = TraceStatus.OK.value
    latency_ms: float = 0.0
    confidence: float = 1.0
    errors: list[dict[str, Any]] = field(default_factory=list)
    next_route: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RawArtifact:
    artifact_id: str
    path: str
    artifact_type: str
    case_id: str = ""
    text: str = ""
    records: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FieldSource:
    field_name: str
    value: Any
    artifact_id: str
    source_path: str
    locator: str
    confidence: float = 1.0
    extraction_method: str = "structured"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PolicyHit:
    rule_id: str
    rule_version: str
    severity: str
    decision_hint: str
    input_fields: dict[str, Any]
    threshold: Any
    calculation: str
    reason: str
    matched: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CasePackage:
    case_id: str
    batch_id: str
    raw_artifacts: list[RawArtifact]
    batch_features: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "batch_id": self.batch_id,
            "raw_artifacts": [a.to_dict() for a in self.raw_artifacts],
            "batch_features": self.batch_features,
        }


class CaseState(TypedDict, total=False):
    batch_id: str
    case_id: str
    raw_artifacts: list[dict[str, Any]]
    batch_features: dict[str, Any]
    parsed_fields: dict[str, Any]
    field_provenance: dict[str, list[dict[str, Any]]]
    policy_hits: list[dict[str, Any]]
    context_info: dict[str, Any]
    reasoning_trace: dict[str, Any]
    decision: dict[str, Any]
    debug_events: list[dict[str, Any]]
    route: str
    errors: list[dict[str, Any]]
    llm_mode: str
    langsmith_enabled: bool


class BatchState(TypedDict, total=False):
    batch_id: str
    source_paths: list[str]
    work_dir: str
    manifest: list[dict[str, Any]]
    case_index: list[dict[str, Any]]
    case_results: list[dict[str, Any]]
    batch_metrics: dict[str, Any]
    error_registry: dict[str, list[dict[str, Any]]]
    debug_events: list[dict[str, Any]]
    llm_mode: str
    max_workers: int


DecisionLiteral = Literal[
    "APPROVE",
    "APPROVE_WITH_FLEX",
    "REJECT",
    "MANUAL_REVIEW",
    "ESCALATE_FRAUD",
]
