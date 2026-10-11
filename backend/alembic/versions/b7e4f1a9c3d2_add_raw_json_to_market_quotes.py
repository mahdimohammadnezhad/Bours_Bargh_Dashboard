"""add raw JSON column to market_quotes

Revision ID: b7e4f1a9c3d2
Revises: a3f7c9d2e1b4
Create Date: 2026-09-05 10:00:00.000000

Collector-specific context that has no dedicated column (a contract's
display name, a market's open/closed status text, etc.) was being parsed
into NormalizedQuote.raw and then discarded before it ever reached the
database - never persisted, and stripped again before every WebSocket
broadcast. The frontend has real, verified fields it needs from this (see
docs/DATA_SOURCES.md) with nowhere to read them from. This column stores
it inline (small payloads, a few hundred bytes) rather than through
raw_ref's file/object-storage indirection (brief §41).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e4f1a9c3d2'
down_revision: Union[str, None] = 'a3f7c9d2e1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("market_quotes", sa.Column("raw", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("market_quotes", "raw")
