"""add agent memory snapshot

Revision ID: 20260608_0003
Revises: 20260606_0002
Create Date: 2026-06-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20260608_0003"
down_revision = "20260606_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_trace", sa.Column("memory_snapshot", mysql.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_trace", "memory_snapshot")
