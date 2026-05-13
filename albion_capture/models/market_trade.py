from datetime import datetime, timezone

from sqlalchemy import BigInteger, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from albion_capture.core.database import Base


class MarketTrade(Base):
    __tablename__ = "market_trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_albion_id: Mapped[str] = mapped_column(String(100), nullable=False)
    city_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    quality_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    timescale: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    item_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    silver_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    avg_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint(
            "item_albion_id", "city_id", "quality_level", "timescale", "timestamp",
            name="uq_market_trades_item_city_ts",
        ),
    )
