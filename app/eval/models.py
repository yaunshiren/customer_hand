from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SafetyBehavior = Literal[
    "allow",
    "flag_prompt_injection",
    "block_unsafe_tool",
    "require_confirmation",
]


class EvalCaseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    writes_state: bool = False
    scenario: str = Field(default="chat", min_length=1)
    setup_turns: list[str] = Field(default_factory=list)
    golden: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scenario")
    @classmethod
    def _normalize_scenario(cls, value: str) -> str:
        return str(value or "chat").strip().lower() or "chat"

    @field_validator("setup_turns")
    @classmethod
    def _clean_setup_turns(cls, values: list[str]) -> list[str]:
        cleaned = [str(value or "").strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("setup_turns must not contain blank messages")
        return cleaned


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    user_input: str = Field(min_length=1)
    expected_intent: str | None
    expected_route: str = Field(min_length=1)
    expected_tool: str | None
    expected_args: dict[str, Any]
    expected_rag_keywords: list[str]
    expected_safety_behavior: SafetyBehavior
    metadata: EvalCaseMetadata = Field(default_factory=EvalCaseMetadata)

    @field_validator("case_id", "user_input", "expected_route")
    @classmethod
    def _clean_required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be blank")
        return text

    @field_validator("expected_intent", "expected_tool")
    @classmethod
    def _clean_optional_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("expected_rag_keywords")
    @classmethod
    def _clean_keywords(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))

    @model_validator(mode="after")
    def _validate_write_contract(self) -> "EvalCase":
        if self.metadata.writes_state and not self.expected_tool:
            raise ValueError("writes_state cases must declare expected_tool")
        return self


class AgentTraceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    intent_id: str | None = None
    route: str | None = None
    rewritten_query: str | None = None
    final_answer: str | None = None
    memory_snapshot: dict[str, Any] | None = None
    latency_ms: int | None = None


class RetrievalTraceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str
    doc_id: str | None = None
    chunk_id: str | None = None
    score: float | None = None
    rerank_score: float | None = None
    content: str | None = None


class ToolTraceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    status: str
    latency_ms: int | None = None


class HttpEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status_code: int
    latency_ms: int = Field(ge=0)
    response_items: list[dict[str, Any]] = Field(default_factory=list)
    error_body: dict[str, Any] | None = None


class TraceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    agent: AgentTraceEvidence | None = None
    retrieval: list[RetrievalTraceEvidence] = Field(default_factory=list)
    tools: list[ToolTraceEvidence] = Field(default_factory=list)
    http: HttpEvidence


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applicable: bool
    passed: bool | None
    expected: Any = None
    actual: Any = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class CaseEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    trace_id: str
    user_input: str
    writes_state: bool
    latency_ms: int
    checks: dict[str, CheckResult]
    task_success: bool
    answer: str | None = None
    actual_intent: str | None = None
    actual_route: str | None = None
    actual_tools: list[str] = Field(default_factory=list)
    retrieved_doc_ids: list[str] = Field(default_factory=list)
    check_evidence: dict[str, Any] = Field(default_factory=dict)
    error_types: list[str] = Field(default_factory=list)
    error_type: str | None = None


class MetricResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numerator: int
    denominator: int
    value: float | None
    not_applicable: bool


class EvalMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_acc: MetricResult
    route_acc: MetricResult
    tool_selection_acc: MetricResult
    tool_args_complete_rate: MetricResult
    rag_hit_at_3: MetricResult
    safety_pass_rate: MetricResult
    task_success_rate: MetricResult
    avg_latency_ms: float | None
    avg_latency_not_applicable: bool


class EvalInfrastructureError(RuntimeError):
    """Raised when the API or trace pipeline cannot produce trustworthy evidence."""
