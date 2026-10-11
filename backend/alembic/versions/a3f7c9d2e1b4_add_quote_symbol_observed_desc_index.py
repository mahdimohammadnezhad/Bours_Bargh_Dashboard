"""add composite index for get_latest_quotes/get_price_history access pattern

Revision ID: a3f7c9d2e1b4
Revises: 1cd027aaf466
Create Date: 2026-08-30 16:15:00.000000

market_service.get_latest_quotes() partitions market_quotes by
(source_id, source_symbol) and orders each partition by observed_at DESC
via a ROW_NUMBER() window function. The existing uq_quote_tick unique
constraint covers these columns but in plain ascending order tied to
equality on all three, which was observed to make SQLite fall back to a
temp b-tree sort per partition once the table grew large (a multi-hour
continuous local test run reached ~700k rows). This index matches the
actual access pattern directly. Also helps get_price_history's
(source_id, source_symbol, observed_at range) query the same way.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f7c9d2e1b4'
down_revision: Union[str, None] = '1cd027aaf466'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_quote_symbol_observed_desc",
        "market_quotes",
        ["source_id", "source_symbol", sa.text("observed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_quote_symbol_observed_desc", table_name="market_quotes")
