from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


IntentType = Literal[
    "KB",
    "TOOL",
    "KB_TOOL",
    "KB_TICKET",
    "TICKET",
    "FLOW",
    "CHITCHAT",
    "UNKNOWN",
]

IntentKind = Literal[
    "KB",
    "MCP",
    "TOOL",
    "TICKET",
    "SYSTEM",
    "FLOW",
    "CHITCHAT",
    "UNKNOWN",
]

IntentLevel = Literal[
    "root",
    "domain",
    "category",
    "intent",
]

IntentSource = Literal[
    "llm_classifier",
    "rule_fallback",
    "unknown",
    "classify_error",
]

ExecutionRoute = Literal[
    "rag",
    "tool",
    "ticket",
    "flow",
    "chitchat",
    "system_response",
    "clarify",
    "fallback",
]


class IntentCandidate(BaseModel):
    intent_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str | None = None


class RoutePolicy(BaseModel):
    execution_route: ExecutionRoute
    system_route: str = Field(min_length=1)
    requires_rag: bool = False
    notes: str | None = None


class IntentGroup(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    parent_id: str | None = None
    level: IntentLevel = "category"
    kind: IntentKind
    description: str = ""


class ClarificationConfig(BaseModel):
    min_confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    min_margin: float = Field(default=0.12, ge=0.0, le=1.0)
    max_candidates: int = Field(default=3, ge=1)
    default_question: str = "我还不太确定你的具体需求，可以补充一下你想咨询的问题吗？"


class IntentDefinition(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)

    # 兼容现有代码：当前分类器、policy、评测主要还依赖 type
    type: IntentType

    # 企业意图树新增字段
    parent_id: str | None = None
    level: IntentLevel = "intent"
    kind: IntentKind | None = None
    route: ExecutionRoute | None = None

    description: str = Field(min_length=1)
    examples: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    negative_examples: list[str] = Field(default_factory=list)

    # 澄清反问
    clarify_question: str | None = None

    # MCP / 工具调用相关
    mcp_tool_id: str | None = None
    required_arguments: list[str] = Field(default_factory=list)

    # 是否参与分类 / 评测，可用于先把工具意图放进树里但不影响当前测试集
    enabled: bool = True
    eval_enabled: bool = True

    route_policy: RoutePolicy | None = None


class IntentResult(BaseModel):
    intent_id: str = Field(min_length=1)
    intent_name: str = Field(min_length=1)
    intent_type: IntentType
    intent_kind: IntentKind | None = None
    route: ExecutionRoute | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    candidates: list[IntentCandidate] = Field(default_factory=list)
    reason: str | None = None
    source: IntentSource = "unknown"

    # 后续做低置信度澄清时会用到
    needs_clarification: bool = False
    clarify_reason: str | None = None
    clarify_question: str | None = None
