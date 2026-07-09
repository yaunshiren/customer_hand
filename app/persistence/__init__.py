"""Persistence infrastructure for trace and eval storage."""

from app.persistence.db import get_engine, ping_trace_db, trace_db_session
from app.persistence.models import (
    AgentTrace,
    ConversationMessage,
    ConversationSummary,
    EvalRecord,
    RetrievalTrace,
    TicketEventRecord,
    TicketRecord,
    ToolTrace,
)
from app.persistence.repositories import (
    AgentTraceCreate,
    EvalRecordUpsert,
    EvalRepository,
    RepositoryError,
    RetrievalTraceCreate,
    ToolTraceCreate,
    TraceRepository,
)
from app.persistence.eval_recorder import EvalPersistSummary, normalize_eval_record, persist_eval_jsonl
from app.persistence.eval_report import default_badcase_report_path, render_badcase_markdown, write_badcase_report
from app.persistence.retrieval_recorder import RetrievalTraceRecorder, record_retrieval_traces
from app.persistence.trace_recorder import AgentTraceRecorder
from app.persistence.tool_recorder import ToolTraceRecorder, record_tool_trace
from app.persistence.ticket_repository import TicketRepository

__all__ = [
    "AgentTrace",
    "AgentTraceCreate",
    "AgentTraceRecorder",
    "EvalRecord",
    "EvalPersistSummary",
    "EvalRecordUpsert",
    "EvalRepository",
    "RepositoryError",
    "RetrievalTrace",
    "RetrievalTraceCreate",
    "RetrievalTraceRecorder",
    "TicketEventRecord",
    "TicketRecord",
    "TicketRepository",
    "ToolTrace",
    "ToolTraceCreate",
    "ToolTraceRecorder",
    "TraceRepository",
    "default_badcase_report_path",
    "get_engine",
    "normalize_eval_record",
    "persist_eval_jsonl",
    "ping_trace_db",
    "record_retrieval_traces",
    "record_tool_trace",
    "render_badcase_markdown",
    "trace_db_session",
    "write_badcase_report",
    "ConversationMessage",
    "ConversationSummary",
]
