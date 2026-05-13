from datetime import datetime, timezone

from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from albion_capture.core.database import Base


class GoldPrice(Base):
    __tablename__ = "gold_prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    price: Mapped[int] = mapped_column(nullable=False)
    timestamp: Mapped[datetime] = mapped_column(unique=True, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
