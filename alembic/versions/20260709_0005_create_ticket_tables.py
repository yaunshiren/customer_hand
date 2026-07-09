"""create ticket and ticket_event tables

Revision ID: 20260709_0005
Revises: 20260624_0004
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20260709_0005"
down_revision = "20260624_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticket",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticket_id", sa.String(length=64), nullable=False),
        sa.Column("ticket_no", sa.String(length=32), nullable=False),
        sa.Column("sender_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", mysql.LONGTEXT(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("suggestion", mysql.LONGTEXT(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", mysql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ux_ticket_ticket_id", "ticket", ["ticket_id"], unique=True)
    op.create_index("ux_ticket_ticket_no", "ticket", ["ticket_no"], unique=True)
    op.create_index("ix_ticket_sender_id", "ticket", ["sender_id"])
    op.create_index("ix_ticket_status", "ticket", ["status"])
    op.create_index("ix_ticket_created_at", "ticket", ["created_at"])

    op.create_table(
        "ticket_event",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticket_record_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=True),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", mysql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.ForeignKeyConstraint(
            ["ticket_record_id"],
            ["ticket.id"],
            name="fk_ticket_event_ticket_record_id",
            ondelete="CASCADE",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_ticket_event_ticket_record_id",
        "ticket_event",
        ["ticket_record_id"],
    )
    op.create_index("ix_ticket_event_event_type", "ticket_event", ["event_type"])
    op.create_index("ix_ticket_event_created_at", "ticket_event", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ticket_event_created_at", table_name="ticket_event")
    op.drop_index("ix_ticket_event_event_type", table_name="ticket_event")
    op.drop_index("ix_ticket_event_ticket_record_id", table_name="ticket_event")
    op.drop_table("ticket_event")

    op.drop_index("ix_ticket_created_at", table_name="ticket")
    op.drop_index("ix_ticket_status", table_name="ticket")
    op.drop_index("ix_ticket_sender_id", table_name="ticket")
    op.drop_index("ux_ticket_ticket_no", table_name="ticket")
    op.drop_index("ux_ticket_ticket_id", table_name="ticket")
    op.drop_table("ticket")
