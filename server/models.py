"""SQLAlchemy models for the central Albion Market server."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    # Guardamos HASH de la key, no la key en plano.
    api_key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    orders_uploaded: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    history_uploaded: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Fingerprint del primer dispositivo/IP que uso la key. Se compara en
    # cada acceso posterior para detectar cambios.
    pinned_ua_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pinned_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pinned_stable_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pinned_hostname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pinned_machine_guid: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AccessLog(Base):
    """Registro cada vez que una API key se usa (header o cookie)."""
    __tablename__ = "access_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_agent: Mapped[str] = mapped_column(String(500), nullable=False)
    ua_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_match: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    path: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)

    # Device fingerprint enriquecido enviado via header X-Device-Info
    stable_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    hostname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    machine_guid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_info: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON completo


class MarketOrder(Base):
    __tablename__ = "market_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    item_albion_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    city_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    quality_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    enchantment_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_price_silver: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    auction_type: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    tier: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    __table_args__ = (
        Index("ix_orders_item_city", "item_albion_id", "city_id"),
        Index("ix_orders_captured", "captured_at"),
    )


class MarketHistory(Base):
    __tablename__ = "market_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_albion_id: Mapped[str] = mapped_column(String(100), nullable=False)
    city_id: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_level: Mapped[int] = mapped_column(Integer, nullable=False)
    timescale: Mapped[int] = mapped_column(Integer, nullable=False)
    item_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    silver_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    avg_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "item_albion_id", "city_id", "quality_level", "timescale", "timestamp",
            name="uq_history",
        ),
        Index("ix_history_item_city", "item_albion_id", "city_id"),
    )


class GoldPrice(Base):
    __tablename__ = "gold_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=True, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
