from datetime import datetime, timezone

from sqlalchemy import BigInteger, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from albion_capture.core.database import Base


class MarketOrder(Base):
    __tablename__ = "market_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    item_albion_id: Mapped[str] = mapped_column(String(100), nullable=False)
    city_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    quality_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    enchantment_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    unit_price_silver: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[int] = mapped_column(nullable=False)
    auction_type: Mapped[str] = mapped_column(String(10), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_market_orders_item_city_type", "item_albion_id", "city_id", "auction_type"),
        Index("ix_market_orders_city_captured", "city_id", "captured_at"),
        Index("ix_market_orders_expires", "expires_at"),
    )
