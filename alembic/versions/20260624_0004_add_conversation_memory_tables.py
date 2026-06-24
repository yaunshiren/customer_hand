"""add conversation memory tables

Revision ID: 20260624_0004
Revises: 20260608_0003
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20260624_0004"
down_revision = "20260608_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_message",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("sender_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", mysql.LONGTEXT(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_conversation_message_sender_id", "conversation_message", ["sender_id"])
    op.create_index(
    "ix_conversation_message_sender_conversation_id",
    "conversation_message",
    ["sender_id", "conversation_id", "id"],
    )
    op.create_index(
        "ix_conversation_message_conversation_id",
        "conversation_message",
        ["conversation_id"],
    )

    op.create_table(
        "conversation_summary",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("sender_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=True),
        sa.Column("last_message_id", sa.BigInteger(), nullable=False),
        sa.Column("content", mysql.LONGTEXT(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_conversation_summary_sender_id", "conversation_summary", ["sender_id"])
    op.create_index(
    "ix_conversation_summary_sender_conversation_last_message_id",
    "conversation_summary",
    ["sender_id", "conversation_id", "last_message_id"],
    )
    op.create_index(
        "ix_conversation_summary_conversation_id",
        "conversation_summary",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_summary_conversation_id", table_name="conversation_summary")
    op.drop_index("ix_conversation_summary_sender_conversation_last_message_id", table_name="conversation_summary")
    op.drop_index("ix_conversation_summary_sender_id", table_name="conversation_summary")
    op.drop_table("conversation_summary")

    op.drop_index("ix_conversation_message_conversation_id", table_name="conversation_message")
    op.drop_index("ix_conversation_message_sender_conversation_id", table_name="conversation_message")
    op.drop_index("ix_conversation_message_sender_id", table_name="conversation_message")
    op.drop_table("conversation_message")