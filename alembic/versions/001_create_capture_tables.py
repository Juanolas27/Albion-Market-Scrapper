"""Create capture tables

Revision ID: 001
Revises:
Create Date: 2026-04-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # market_orders
    op.create_table(
        "market_orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("item_albion_id", sa.String(100), nullable=False),
        sa.Column("city_id", sa.SmallInteger(), nullable=False),
        sa.Column("quality_level", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("enchantment_level", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("unit_price_silver", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("auction_type", sa.String(10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
    )
    op.create_index(
        "ix_market_orders_item_city_type",
        "market_orders",
        ["item_albion_id", "city_id", "auction_type"],
    )
    op.create_index(
        "ix_market_orders_city_captured",
        "market_orders",
        ["city_id", "captured_at"],
    )
    op.create_index(
        "ix_market_orders_expires",
        "market_orders",
        ["expires_at"],
    )

    # market_trades
    op.create_table(
        "market_trades",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_albion_id", sa.String(100), nullable=False),
        sa.Column("city_id", sa.SmallInteger(), nullable=False),
        sa.Column("quality_level", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("timescale", sa.SmallInteger(), nullable=False),
        sa.Column("item_amount", sa.BigInteger(), nullable=False),
        sa.Column("silver_amount", sa.BigInteger(), nullable=False),
        sa.Column("avg_price", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "item_albion_id", "city_id", "quality_level", "timescale", "timestamp",
            name="uq_market_trades_item_city_ts",
        ),
    )

    # gold_prices
    op.create_table(
        "gold_prices",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("timestamp"),
    )

    # capture_sessions
    op.create_table(
        "capture_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("city_name", sa.String(50), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("local_port", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("packets_captured", sa.BigInteger(), server_default="0"),
        sa.Column("orders_extracted", sa.BigInteger(), server_default="0"),
        sa.Column("status", sa.String(20), server_default="'running'"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("capture_sessions")
    op.drop_table("gold_prices")
    op.drop_table("market_trades")
    op.drop_table("market_orders")
