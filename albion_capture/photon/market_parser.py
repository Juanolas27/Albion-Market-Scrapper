"""Parse market data from decoded Photon operation response parameters.

Albion sends market data as JSON strings in parameter 0.
The real operation code is in parameter 253.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from albion_capture.core.logging import get_logger

log = get_logger("market_parser")

# Albion parameter keys
PARAM_DATA = 0          # List of JSON strings with market orders/history
PARAM_OP_CODE = 253     # Real Albion operation code
PARAM_RETURN_CODE = 255


@dataclass
class MarketOrderData:
    order_id: int
    item_albion_id: str
    unit_price_silver: int
    amount: int
    auction_type: str  # "offer" (sell) or "request" (buy)
    quality_level: int = 1
    enchantment_level: int = 0
    expires_at: datetime | None = None
    city_id: int = 0
    tier: int = 0


@dataclass
class MarketHistoryData:
    item_albion_id: str
    city_id: int
    quality_level: int
    timescale: int
    item_amount: int
    silver_amount: int
    avg_price: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GoldPriceData:
    price: int
    timestamp: datetime


def parse_market_orders(params: dict, city_id: int) -> list[MarketOrderData]:
    """Parse market offers/requests from operation response.

    Works for both op 74 (sell offers) and op 75 (buy requests).
    Parameter 0 contains a list of JSON strings, each representing an order.
    """
    orders = []
    raw_list = params.get(PARAM_DATA)

    if not raw_list:
        return orders

    if not isinstance(raw_list, list):
        raw_list = [raw_list]

    for item in raw_list:
        try:
            if isinstance(item, str):
                data = json.loads(item)
            elif isinstance(item, dict):
                data = item
            else:
                continue

            order = MarketOrderData(
                order_id=int(data.get("Id", 0)),
                item_albion_id=str(data.get("ItemTypeId", "")),
                unit_price_silver=int(data.get("UnitPriceSilver", 0)),
                amount=int(data.get("Amount", 0)),
                auction_type=str(data.get("AuctionType", "offer")).lower(),
                quality_level=int(data.get("QualityLevel", 1)),
                enchantment_level=int(data.get("EnchantmentLevel", 0)),
                tier=int(data.get("Tier", 0)),
                city_id=city_id,
                expires_at=_parse_timestamp(data.get("Expires")),
            )

            if order.order_id and order.item_albion_id:
                orders.append(order)

        except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
            log.debug("order_parse_error", error=str(e))
            continue

    log.info("orders_parsed", count=len(orders), city_id=city_id)
    return orders


def parse_market_history(params: dict, city_id: int) -> list[MarketHistoryData]:
    """Parse market history from operation 88 response."""
    histories = []
    raw_list = params.get(PARAM_DATA)

    if not raw_list:
        return histories

    if not isinstance(raw_list, list):
        raw_list = [raw_list]

    for item in raw_list:
        try:
            if isinstance(item, str):
                data = json.loads(item)
            elif isinstance(item, dict):
                data = item
            else:
                continue

            history = MarketHistoryData(
                item_albion_id=str(data.get("ItemTypeId", "")),
                city_id=city_id,
                quality_level=int(data.get("QualityLevel", 1)),
                timescale=int(data.get("Timescale", 0)),
                item_amount=int(data.get("ItemAmount", 0)),
                silver_amount=int(data.get("SilverAmount", 0)),
                avg_price=int(data.get("AveragePrice", 0)),
                timestamp=_parse_timestamp(data.get("Timestamp")) or datetime.now(timezone.utc),
            )
            histories.append(history)

        except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
            log.debug("history_parse_error", error=str(e))
            continue

    log.info("history_parsed", count=len(histories), city_id=city_id)
    return histories


def parse_gold_prices(params: dict) -> list[GoldPriceData]:
    """Parse gold market info from operation 237 response."""
    prices = []
    raw_list = params.get(PARAM_DATA)

    if not raw_list:
        return prices

    if not isinstance(raw_list, list):
        raw_list = [raw_list]

    for item in raw_list:
        try:
            if isinstance(item, str):
                data = json.loads(item)
            elif isinstance(item, dict):
                data = item
            else:
                continue

            prices.append(GoldPriceData(
                price=int(data.get("Price", 0)),
                timestamp=_parse_timestamp(data.get("Timestamp")) or datetime.now(timezone.utc),
            ))

        except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
            log.debug("gold_parse_error", error=str(e))
            continue

    log.info("gold_prices_parsed", count=len(prices))
    return prices


def get_albion_op_code(params: dict) -> int | None:
    """Get the real Albion operation code from parameter 253."""
    op = params.get(PARAM_OP_CODE)
    if isinstance(op, int):
        return op
    return None


def _parse_timestamp(value) -> datetime | None:
    """Parse a timestamp value from Albion JSON."""
    if value is None:
        return None

    try:
        if isinstance(value, str):
            # ISO format: "2024-01-15T10:30:00.000Z"
            cleaned = value.replace("Z", "+00:00")
            return datetime.fromisoformat(cleaned)
        elif isinstance(value, (int, float)):
            if value > 1e15:
                # .NET ticks
                unix_seconds = (value - 621355968000000000) / 10_000_000
                return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
            elif value > 1e12:
                return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            else:
                return datetime.fromtimestamp(value, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        pass

    return None
