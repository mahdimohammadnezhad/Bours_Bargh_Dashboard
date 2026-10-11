"""add weather_daily table

Revision ID: c4d8e2a6f1b3
Revises: b7e4f1a9c3d2
Create Date: 2026-10-11 15:00:00.000000

Daily temperatures (observed and forecast) behind the temperature/season
price forecast - see app/services/weather.py and app/analytics/forecast.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d8e2a6f1b3'
down_revision: Union[str, None] = 'b7e4f1a9c3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weather_daily",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("location", sa.String(length=32), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("t_mean", sa.Float(), nullable=True),
        sa.Column("t_max", sa.Float(), nullable=True),
        sa.Column("t_min", sa.Float(), nullable=True),
        sa.Column("is_forecast", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("location", "day", name="uq_weather_location_day"),
    )
    op.create_index("ix_weather_daily_location", "weather_daily", ["location"])
    op.create_index("ix_weather_daily_day", "weather_daily", ["day"])


def downgrade() -> None:
    op.drop_index("ix_weather_daily_day", table_name="weather_daily")
    op.drop_index("ix_weather_daily_location", table_name="weather_daily")
    op.drop_table("weather_daily")
