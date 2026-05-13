"""Batch database writer for market data with upsert support."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from albion_capture.core.logging import get_logger
from albion_capture.models.capture_session import CaptureSession
from albion_capture.models.gold_price import GoldPrice
from albion_capture.models.market_order import MarketOrder
from albion_capture.models.market_trade import MarketTrade
from albion_capture.photon.market_parser import (
    GoldPriceData,
    MarketHistoryData,
    MarketOrderData,
)

log = get_logger("db_writer")


class DBWriter:
    """Buffers market data and writes in batches to PostgreSQL."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        batch_size: int = 100,
        flush_interval: int = 5,
        city_name: str = "",
    ):
        self._session_factory = session_factory
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._city_name = city_name

        self._order_buffer: list[MarketOrderData] = []
        self._history_buffer: list[MarketHistoryData] = []
        self._gold_buffer: list[GoldPriceData] = []
        self._lock = threading.Lock()

        self._orders_written = 0
        self._histories_written = 0

        self._flush_timer: threading.Timer | None = None
        self._running = False

    def start(self) -> None:
        """Start the periodic flush timer."""
        self._running = True
        self._schedule_flush()

    def stop(self) -> None:
        """Stop the flush timer and flush remaining data."""
        self._running = False
        if self._flush_timer:
            self._flush_timer.cancel()
        self._flush()

    @property
    def orders_written(self) -> int:
        return self._orders_written

    @property
    def histories_written(self) -> int:
        return self._histories_written

    def add_orders(self, orders: list[MarketOrderData]) -> None:
        """Add market orders to the write buffer."""
        with self._lock:
            self._order_buffer.extend(orders)
            if len(self._order_buffer) >= self._batch_size:
                self._flush_orders()

    def add_histories(self, histories: list[MarketHistoryData]) -> None:
        """Add market history entries to the write buffer."""
        with self._lock:
            self._history_buffer.extend(histories)
            if len(self._history_buffer) >= self._batch_size:
                self._flush_histories()

    def add_gold_prices(self, prices: list[GoldPriceData]) -> None:
        """Add gold price entries to the write buffer."""
        with self._lock:
            self._gold_buffer.extend(prices)
            if len(self._gold_buffer) >= self._batch_size:
                self._flush_gold()

    def _schedule_flush(self) -> None:
        """Schedule the next periodic flush."""
        if self._running:
            self._flush_timer = threading.Timer(self._flush_interval, self._timed_flush)
            self._flush_timer.daemon = True
            self._flush_timer.start()

    def _timed_flush(self) -> None:
        """Flush all buffers on timer."""
        self._flush()
        self._schedule_flush()

    def _flush(self) -> None:
        """Flush all buffers to the database."""
        with self._lock:
            self._flush_orders()
            self._flush_histories()
            self._flush_gold()

    def _flush_orders(self) -> None:
        """Write buffered orders to database using upsert."""
        if not self._order_buffer:
            return

        orders = self._order_buffer[:]
        self._order_buffer.clear()

        try:
            session = self._session_factory()
            try:
                now = datetime.now(timezone.utc)
                stmt = text("""
                    INSERT INTO market_orders
                        (order_id, item_albion_id, city_id, quality_level,
                         enchantment_level, unit_price_silver, amount,
                         auction_type, expires_at, captured_at, updated_at)
                    VALUES
                        (:order_id, :item_albion_id, :city_id, :quality_level,
                         :enchantment_level, :unit_price_silver, :amount,
                         :auction_type, :expires_at, :captured_at, :updated_at)
                    ON CONFLICT (order_id) DO UPDATE SET
                        unit_price_silver = EXCLUDED.unit_price_silver,
                        amount = EXCLUDED.amount,
                        updated_at = EXCLUDED.updated_at
                """)

                params = [
                    {
                        "order_id": o.order_id,
                        "item_albion_id": o.item_albion_id,
                        "city_id": o.city_id,
                        "quality_level": o.quality_level,
                        "enchantment_level": o.enchantment_level,
                        "unit_price_silver": o.unit_price_silver,
                        "amount": o.amount,
                        "auction_type": o.auction_type,
                        "expires_at": o.expires_at,
                        "captured_at": now,
                        "updated_at": now,
                    }
                    for o in orders
                ]

                session.execute(stmt, params)
                session.commit()
                self._orders_written += len(orders)
                log.info(
                    "orders_flushed",
                    count=len(orders),
                    city=self._city_name,
                    total=self._orders_written,
                )
            except Exception as e:
                session.rollback()
                log.error("orders_flush_error", error=str(e), count=len(orders))
                # Put orders back in buffer for retry
                self._order_buffer = orders + self._order_buffer
            finally:
                session.close()
        except Exception as e:
            log.error("db_connection_error", error=str(e))
            self._order_buffer = orders + self._order_buffer

    def _flush_histories(self) -> None:
        """Write buffered history entries to database."""
        if not self._history_buffer:
            return

        histories = self._history_buffer[:]
        self._history_buffer.clear()

        try:
            session = self._session_factory()
            try:
                now = datetime.now(timezone.utc)
                stmt = text("""
                    INSERT INTO market_trades
                        (item_albion_id, city_id, quality_level, timescale,
                         item_amount, silver_amount, avg_price, timestamp, captured_at)
                    VALUES
                        (:item_albion_id, :city_id, :quality_level, :timescale,
                         :item_amount, :silver_amount, :avg_price, :timestamp, :captured_at)
                    ON CONFLICT ON CONSTRAINT uq_market_trades_item_city_ts DO UPDATE SET
                        item_amount = EXCLUDED.item_amount,
                        silver_amount = EXCLUDED.silver_amount,
                        avg_price = EXCLUDED.avg_price,
                        captured_at = EXCLUDED.captured_at
                """)

                params = [
                    {
                        "item_albion_id": h.item_albion_id,
                        "city_id": h.city_id,
                        "quality_level": h.quality_level,
                        "timescale": h.timescale,
                        "item_amount": h.item_amount,
                        "silver_amount": h.silver_amount,
                        "avg_price": h.avg_price,
                        "timestamp": h.timestamp,
                        "captured_at": now,
                    }
                    for h in histories
                ]

                session.execute(stmt, params)
                session.commit()
                self._histories_written += len(histories)
                log.info("histories_flushed", count=len(histories), city=self._city_name)
            except Exception as e:
                session.rollback()
                log.error("histories_flush_error", error=str(e))
                self._history_buffer = histories + self._history_buffer
            finally:
                session.close()
        except Exception as e:
            log.error("db_connection_error", error=str(e))
            self._history_buffer = histories + self._history_buffer

    def _flush_gold(self) -> None:
        """Write buffered gold prices to database."""
        if not self._gold_buffer:
            return

        prices = self._gold_buffer[:]
        self._gold_buffer.clear()

        try:
            session = self._session_factory()
            try:
                stmt = text("""
                    INSERT INTO gold_prices (price, timestamp, captured_at)
                    VALUES (:price, :timestamp, :captured_at)
                    ON CONFLICT (timestamp) DO UPDATE SET
                        price = EXCLUDED.price,
                        captured_at = EXCLUDED.captured_at
                """)

                now = datetime.now(timezone.utc)
                params = [
                    {
                        "price": p.price,
                        "timestamp": p.timestamp,
                        "captured_at": now,
                    }
                    for p in prices
                ]

                session.execute(stmt, params)
                session.commit()
                log.info("gold_prices_flushed", count=len(prices))
            except Exception as e:
                session.rollback()
                log.error("gold_flush_error", error=str(e))
                self._gold_buffer = prices + self._gold_buffer
            finally:
                session.close()
        except Exception as e:
            log.error("db_connection_error", error=str(e))
            self._gold_buffer = prices + self._gold_buffer
