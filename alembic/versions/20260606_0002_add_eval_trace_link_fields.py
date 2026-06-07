"""add eval trace link fields

Revision ID: 20260606_0002
Revises: 20260604_0001
Create Date: 2026-06-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260606_0002"
down_revision = "20260604_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("eval_record", sa.Column("trace_id", sa.String(length=64), nullable=True))
    op.add_column("eval_record", sa.Column("system_route", sa.String(length=64), nullable=True))
    op.add_column("eval_record", sa.Column("eval_mode", sa.String(length=32), nullable=True))
    op.create_index("ix_eval_record_trace_id", "eval_record", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_eval_record_trace_id", table_name="eval_record")
    op.drop_column("eval_record", "eval_mode")
    op.drop_column("eval_record", "system_route")
    op.drop_column("eval_record", "trace_id")
