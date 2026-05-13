"""Pydantic schemas for request/response bodies."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict


class OrderIn(BaseModel):
    order_id: int
    item_albion_id: str
    city_id: int
    quality_level: int = 1
    enchantment_level: int = 0
    unit_price_silver: int
    amount: int
    auction_type: str = Field(pattern="^(offer|request)$")
    tier: int = 0
    expires_at: datetime | None = None


class HistoryIn(BaseModel):
    item_albion_id: str
    city_id: int
    quality_level: int
    timescale: int
    item_amount: int
    silver_amount: int
    avg_price: int
    timestamp: datetime


class GoldIn(BaseModel):
    price: int
    timestamp: datetime


class UploadResponse(BaseModel):
    received: int
    inserted: int
    updated: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    disabled: bool
    is_admin: bool = False
    created_at: datetime
    last_seen_at: datetime | None
    orders_uploaded: int
    history_uploaded: int


class MeOut(BaseModel):
    id: int
    name: str
    is_admin: bool
    contributions_today: int = 0
    threshold: int = 4000
    allowed: bool = True


class AdminCreateUserIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class AdminRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class AdminKeyOut(BaseModel):
    id: int
    name: str
    api_key: str


class StatsOut(BaseModel):
    total_orders: int
    total_history: int
    total_users: int
    cities: dict[int, int]
    top_contributors: list[dict]
