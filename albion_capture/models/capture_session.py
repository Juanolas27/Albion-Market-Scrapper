from datetime import datetime, timezone

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from albion_capture.core.database import Base


class CaptureSession(Base):
    __tablename__ = "capture_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    city_name: Mapped[str] = mapped_column(String(50), nullable=False)
    city_id: Mapped[int] = mapped_column(nullable=False)
    local_port: Mapped[int] = mapped_column(nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    last_heartbeat: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    packets_captured: Mapped[int] = mapped_column(BigInteger, default=0)
    orders_extracted: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")
