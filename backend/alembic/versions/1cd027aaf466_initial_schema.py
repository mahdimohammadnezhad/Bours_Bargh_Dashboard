"""initial schema

Revision ID: 1cd027aaf466
Revises:
Create Date: 2026-08-20 16:47:37.198940

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1cd027aaf466'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(1024), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "instruments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("market_segment", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"], unique=True)

    op.create_table(
        "source_instruments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("source_symbol", sa.String(128), nullable=False),
        sa.UniqueConstraint("source_id", "source_symbol", name="uq_source_symbol"),
    )

    op.create_table(
        "market_quotes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("source_symbol", sa.String(128), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), sa.ForeignKey("instruments.id"), nullable=True),
        sa.Column("last_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("close_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("price_change", sa.Numeric(18, 4), nullable=True),
        sa.Column("price_change_percent", sa.Numeric(9, 4), nullable=True),
        sa.Column("volume", sa.Numeric(20, 4), nullable=True),
        sa.Column("value", sa.Numeric(24, 4), nullable=True),
        sa.Column("transaction_count", sa.Integer(), nullable=True),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_ref", sa.String(512), nullable=True),
        sa.UniqueConstraint("source_id", "source_symbol", "observed_at", name="uq_quote_tick"),
    )
    op.create_index("ix_market_quotes_observed_at", "market_quotes", ["observed_at"])
    op.create_index("ix_market_quotes_source_id", "market_quotes", ["source_id"])
    op.create_index("ix_market_quotes_source_symbol", "market_quotes", ["source_symbol"])

    op.create_table(
        "collector_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("records_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(1024), nullable=True),
    )
    op.create_index("ix_collector_logs_source_id", "collector_logs", ["source_id"])
    op.create_index("ix_collector_logs_started_at", "collector_logs", ["started_at"])

    op.create_table(
        "system_health",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("stale_seconds", sa.Float(), nullable=True),
    )
    op.create_index("ix_system_health_source_id", "system_health", ["source_id"])


def downgrade() -> None:
    op.drop_table("system_health")
    op.drop_table("collector_logs")
    op.drop_table("market_quotes")
    op.drop_table("source_instruments")
    op.drop_table("instruments")
    op.drop_table("data_sources")
