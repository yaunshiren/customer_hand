"""create trace and eval tables

Revision ID: 20260604_0001
Revises:
Create Date: 2026-06-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20260604_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_trace",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("sender_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=True),
        sa.Column("user_text", mysql.LONGTEXT(), nullable=False),
        sa.Column("rewritten_query", mysql.LONGTEXT(), nullable=True),
        sa.Column("intent_id", sa.String(length=128), nullable=True),
        sa.Column("intent_confidence", sa.Float(), nullable=True),
        sa.Column("route", sa.String(length=64), nullable=True),
        sa.Column("final_answer", mysql.LONGTEXT(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("ix_agent_trace_sender_id", "agent_trace", ["sender_id"])
    op.create_index("ix_agent_trace_conversation_id", "agent_trace", ["conversation_id"])
    op.create_index("ix_agent_trace_created_at", "agent_trace", ["created_at"])

    op.create_table(
        "retrieval_trace",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("query", mysql.LONGTEXT(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("doc_id", sa.String(length=128), nullable=True),
        sa.Column("chunk_id", sa.String(length=128), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("content", mysql.LONGTEXT(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("ix_retrieval_trace_trace_id", "retrieval_trace", ["trace_id"])
    op.create_index("ix_retrieval_trace_doc_id", "retrieval_trace", ["doc_id"])
    op.create_index("ix_retrieval_trace_chunk_id", "retrieval_trace", ["chunk_id"])
    op.create_index("ix_retrieval_trace_channel", "retrieval_trace", ["channel"])

    op.create_table(
        "tool_trace",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("arguments_json", mysql.JSON(), nullable=True),
        sa.Column("result_json", mysql.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("ix_tool_trace_trace_id", "tool_trace", ["trace_id"])
    op.create_index("ix_tool_trace_tool_name", "tool_trace", ["tool_name"])
    op.create_index("ix_tool_trace_status", "tool_trace", ["status"])

    op.create_table(
        "eval_record",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("question", mysql.LONGTEXT(), nullable=False),
        sa.Column("expected_intent", sa.String(length=128), nullable=True),
        sa.Column("predicted_intent", sa.String(length=128), nullable=True),
        sa.Column("expected_doc_ids", mysql.JSON(), nullable=True),
        sa.Column("retrieved_doc_ids", mysql.JSON(), nullable=True),
        sa.Column("answer", mysql.LONGTEXT(), nullable=True),
        sa.Column("is_hit", sa.Boolean(), nullable=True),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("ix_eval_record_run_id", "eval_record", ["run_id"])
    op.create_index("ix_eval_record_case_id", "eval_record", ["case_id"])
    op.create_index("ix_eval_record_run_case", "eval_record", ["run_id", "case_id"], unique=True)
    op.create_index("ix_eval_record_error_type", "eval_record", ["error_type"])


def downgrade() -> None:
    op.drop_table("eval_record")
    op.drop_table("tool_trace")
    op.drop_table("retrieval_trace")
    op.drop_table("agent_trace")
