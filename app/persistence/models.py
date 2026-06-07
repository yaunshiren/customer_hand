from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Float, Index, Integer, String, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AgentTrace(Base):
    __tablename__ = "agent_trace"
    __table_args__ = (
        Index("ix_agent_trace_sender_id", "sender_id"),
        Index("ix_agent_trace_conversation_id", "conversation_id"),
        Index("ix_agent_trace_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sender_id: Mapped[str] = mapped_column(String(128), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_text: Mapped[str] = mapped_column(mysql.LONGTEXT(), nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(mysql.LONGTEXT(), nullable=True)
    intent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    intent_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    route: Mapped[str | None] = mapped_column(String(64), nullable=True)
    final_answer: Mapped[str | None] = mapped_column(mysql.LONGTEXT(), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )


class RetrievalTrace(Base):
    __tablename__ = "retrieval_trace"
    __table_args__ = (
        Index("ix_retrieval_trace_trace_id", "trace_id"),
        Index("ix_retrieval_trace_doc_id", "doc_id"),
        Index("ix_retrieval_trace_chunk_id", "chunk_id"),
        Index("ix_retrieval_trace_channel", "channel"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[str] = mapped_column(mysql.LONGTEXT(), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    doc_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rerank_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    content: Mapped[str | None] = mapped_column(mysql.LONGTEXT(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )


class ToolTrace(Base):
    __tablename__ = "tool_trace"
    __table_args__ = (
        Index("ix_tool_trace_trace_id", "trace_id"),
        Index("ix_tool_trace_tool_name", "tool_name"),
        Index("ix_tool_trace_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(mysql.JSON(), nullable=True)
    result_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(mysql.JSON(), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )


class EvalRecord(Base):
    __tablename__ = "eval_record"
    __table_args__ = (
        Index("ix_eval_record_run_id", "run_id"),
        Index("ix_eval_record_case_id", "case_id"),
        Index("ix_eval_record_run_case", "run_id", "case_id", unique=True),
        Index("ix_eval_record_error_type", "error_type"),
        Index("ix_eval_record_trace_id", "trace_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(128), nullable=False)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    question: Mapped[str] = mapped_column(mysql.LONGTEXT(), nullable=False)
    expected_intent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    predicted_intent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expected_doc_ids: Mapped[list[str] | None] = mapped_column(mysql.JSON(), nullable=True)
    retrieved_doc_ids: Mapped[list[str] | None] = mapped_column(mysql.JSON(), nullable=True)
    answer: Mapped[str | None] = mapped_column(mysql.LONGTEXT(), nullable=True)
    is_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    system_route: Mapped[str | None] = mapped_column(String(64), nullable=True)
    eval_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )
