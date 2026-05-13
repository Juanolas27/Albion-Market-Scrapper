"""City worker: captures, parses, and stores market data for a single city."""
from __future__ import annotations

import multiprocessing
import signal
import threading
import time
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from albion_capture.capture.sniffer import AlbionSniffer
from albion_capture.core.config import CaptureConfig, DatabaseConfig, WorkerConfig
from albion_capture.core.database import create_session_factory
from albion_capture.core.logging import get_logger, setup_logging
from albion_capture.models.capture_session import CaptureSession
from albion_capture.photon.decoder import PhotonDecoder
from albion_capture.photon.market_parser import (
    get_albion_op_code,
    parse_gold_prices,
    parse_market_history,
    parse_market_orders,
)
import os

from albion_capture.photon.operations import CITY_IDS, CITY_NAMES, OperationCodes

# Patrones de nombre de cluster -> city_id (para detectar por subcadena)
# Albion usa strings como "BrecilienMarket", "4002-Brecilien", "MartlockMarket", etc.
CITY_NAME_PATTERNS = {
    "brecilien": 4002,
    "martlock": 3004,
    "bridgewatch": 3005,
    "fortsterling": 3002,
    "fort sterling": 3002,
    "lymhurst": 3003,
    "thetford": 3000,
    "caerleon": 3008,
    "blackmarket": 3013,
    "black market": 3013,
}

CITY_DETECT_DEBUG = os.environ.get("CITY_DETECT_DEBUG", "").lower() in ("1", "true", "yes")
from albion_capture.workers.db_writer import DBWriter

log = get_logger("city_worker")


class CityWorker:
    """Worker process for capturing market data from a single city.

    Each worker:
    - Sniffs UDP packets filtered to its assigned local port
    - Decodes Photon Protocol16 messages
    - Extracts market data from operation responses
    - Batch-writes to PostgreSQL
    """

    def __init__(
        self,
        worker_config: WorkerConfig,
        db_config: DatabaseConfig,
        capture_config: CaptureConfig,
    ):
        self.worker_config = worker_config
        self.db_config = db_config
        self.capture_config = capture_config

        self._running = False
        self._session_factory: sessionmaker | None = None
        self._sniffer: AlbionSniffer | None = None
        self._decoder: PhotonDecoder | None = None
        self._db_writer: DBWriter | None = None
        self._session_id: int | None = None
        # Ciudad detectada dinamicamente por los paquetes (auto-sigue al jugador)
        self._current_city_id: int = self.worker_config.city_id
        self._known_city_ids: set[int] = set(CITY_IDS.values())

    @property
    def city(self) -> str:
        return self.worker_config.city

    @property
    def city_id(self) -> int:
        return self.worker_config.city_id

    @property
    def local_port(self) -> int | None:
        return self.worker_config.local_port

    @property
    def local_ports(self) -> list[int]:
        ports = self.worker_config.local_ports
        if not ports and self.worker_config.local_port:
            ports = [self.worker_config.local_port]
        return ports

    def run(self) -> None:
        """Main worker loop. Called in a subprocess."""
        setup_logging()
        log.info("worker_starting", city=self.city, ports=self.local_ports)

        if not self.local_ports:
            log.error("no_local_ports", city=self.city)
            return

        # Setup components
        self._session_factory = create_session_factory(self.db_config)

        self._db_writer = DBWriter(
            session_factory=self._session_factory,
            batch_size=self.capture_config.batch_size,
            flush_interval=self.capture_config.flush_interval_seconds,
            city_name=self.city,
        )

        self._decoder = PhotonDecoder(
            on_response=self._on_response,
            on_event=self._on_event,
        )

        self._sniffer = AlbionSniffer(
            game_port=self.capture_config.game_port,
            local_ports=self.local_ports,
            callback=self._on_packet,
        )

        # Register session
        self._register_session()

        # Handle signals
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        # Start components
        self._running = True
        self._db_writer.start()
        self._sniffer.start()

        log.info("worker_running", city=self.city, port=self.local_port)

        # Heartbeat + stats loop
        try:
            while self._running:
                time.sleep(self.capture_config.heartbeat_interval_seconds)
                self._update_heartbeat()
                self._log_stats()
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _log_stats(self) -> None:
        """Log capture statistics for monitoring."""
        decoder_stats = self._decoder.stats if self._decoder else {}
        log.info(
            "worker_stats",
            city=self.city,
            packets=self._sniffer.packet_count if self._sniffer else 0,
            responses=decoder_stats.get("responses", 0),
            events=decoder_stats.get("events", 0),
            fragments=decoder_stats.get("fragments_reassembled", 0),
            encrypted=decoder_stats.get("encrypted", 0),
            errors=decoder_stats.get("errors", 0),
            orders_written=self._db_writer.orders_written if self._db_writer else 0,
            histories_written=self._db_writer.histories_written if self._db_writer else 0,
        )

    def _signal_handler(self, signum, frame) -> None:
        log.info("signal_received", signal=signum, city=self.city)
        self._running = False

    def _shutdown(self) -> None:
        """Clean shutdown of all components."""
        log.info("worker_shutting_down", city=self.city)

        if self._sniffer:
            self._sniffer.stop()
        if self._db_writer:
            self._db_writer.stop()

        self._update_session_status("stopped")
        log.info(
            "worker_stopped",
            city=self.city,
            packets=self._sniffer.packet_count if self._sniffer else 0,
            orders_written=self._db_writer.orders_written if self._db_writer else 0,
        )

    def _on_packet(
        self,
        raw_data: bytes,
        src_ip: str,
        src_port: int,
        dst_ip: str,
        dst_port: int,
    ) -> None:
        """Called for each captured UDP packet."""
        if self._decoder:
            self._decoder.handle_payload(raw_data)

    # Strings EXACTAS que identifican cada ciudad (cluster names del server)
    _EXACT_CITY_STRINGS = {
        # Formatos conocidos de cluster IDs
        "3000": 3000, "3002": 3002, "3003": 3003, "3004": 3004,
        "3005": 3005, "3008": 3008, "3013": 3013, "4002": 4002,
        "@3000": 3000, "@3002": 3002, "@3003": 3003, "@3004": 3004,
        "@3005": 3005, "@3008": 3008, "@3013": 3013, "@4002": 4002,
        # Nombres de ciudades
        "Thetford": 3000, "Fort Sterling": 3002, "Lymhurst": 3003,
        "Martlock": 3004, "Bridgewatch": 3005, "Caerleon": 3008,
        "Black Market": 3013, "Brecilien": 4002,
        # Brecilien usa varios alias (ajustar segun debug):
        "BrecilienMarket": 4002, "BrecilienDocks": 4002,
        "4002-BrecilienMarket": 4002, "4002-Brecilien": 4002,
    }

    def _detect_city(self, params: dict) -> None:
        """Detecta ciudad a partir de params de ops NO-market.

        Solo matches EXACTOS para evitar falsos positivos con metadata de items.
        """
        for val in params.values():
            if isinstance(val, int) and val in self._known_city_ids:
                self._update_current_city(val)
                return
            if isinstance(val, str):
                s = val.strip()
                if s in self._EXACT_CITY_STRINGS:
                    self._update_current_city(self._EXACT_CITY_STRINGS[s])
                    return
                # Debug: loggear strings plausibles (cortas, sin espacios raros)
                if CITY_DETECT_DEBUG and 3 < len(s) < 60 and "{" not in s:
                    log.info("city_detect_unknown_string", value=s)

    def _update_current_city(self, city_id: int) -> None:
        if city_id != self._current_city_id:
            old_name = CITY_NAMES.get(self._current_city_id, str(self._current_city_id))
            new_name = CITY_NAMES.get(city_id, str(city_id))
            log.info("city_changed", from_city=old_name, to_city=new_name)
            self._current_city_id = city_id

    # Ops de market donde NO hay que detectar ciudad (contienen metadata de
    # items que falsea la deteccion por subcadena: "Thetford", "Lymhurst", etc.)
    _MARKET_OPS = {
        OperationCodes.AUCTION_GET_OFFERS,
        OperationCodes.AUCTION_GET_REQUESTS,
        OperationCodes.AUCTION_GET_ITEM_AVERAGE_STATS,
        OperationCodes.GOLD_MARKET_GET_INFOS,
    }

    def _on_response(self, op_code: int, params: dict) -> None:
        """Handle a decoded Photon operation response.

        Albion puts the real operation code in parameter 253.
        """
        albion_op = get_albion_op_code(params) or op_code

        # Auto-deteccion de ciudad solo en modo debug (desactivada por defecto
        # porque los eventos de Photon dan falsos positivos). La ciudad se
        # fija desde run_workers.py al arrancar.
        if CITY_DETECT_DEBUG and albion_op not in self._MARKET_OPS:
            self._detect_city(params)

        city_id = self._current_city_id
        city_name = CITY_NAMES.get(city_id, self.city)

        if albion_op in (OperationCodes.AUCTION_GET_OFFERS, OperationCodes.AUCTION_GET_REQUESTS):
            orders = parse_market_orders(params, city_id)
            if orders and self._db_writer:
                self._db_writer.add_orders(orders)
                log.info("market_orders_captured", city=city_name, count=len(orders), op=albion_op)

        elif albion_op == OperationCodes.AUCTION_GET_ITEM_AVERAGE_STATS:
            histories = parse_market_history(params, city_id)
            if histories and self._db_writer:
                self._db_writer.add_histories(histories)
                log.info("market_history_captured", city=city_name, count=len(histories))

        elif albion_op == OperationCodes.GOLD_MARKET_GET_INFOS:
            prices = parse_gold_prices(params)
            if prices and self._db_writer:
                self._db_writer.add_gold_prices(prices)
                log.info("gold_prices_captured", count=len(prices))

    def _on_event(self, event_code: int, params: dict) -> None:
        """Handle a decoded Photon event."""
        if CITY_DETECT_DEBUG:
            self._detect_city(params)

    def _register_session(self) -> None:
        """Register this worker session in the database."""
        if not self._session_factory:
            return

        try:
            session = self._session_factory()
            try:
                capture_session = CaptureSession(
                    city_name=self.city,
                    city_id=self.city_id,
                    local_port=self.local_ports[0] if self.local_ports else 0,
                    status="running",
                )
                session.add(capture_session)
                session.commit()
                self._session_id = capture_session.id
                log.info("session_registered", session_id=self._session_id)
            except Exception as e:
                session.rollback()
                log.error("session_register_error", error=str(e))
            finally:
                session.close()
        except Exception as e:
            log.error("db_connection_error", error=str(e))

    def _update_heartbeat(self) -> None:
        """Update session heartbeat and stats."""
        if not self._session_factory or not self._session_id:
            return

        try:
            session = self._session_factory()
            try:
                capture_session = session.get(CaptureSession, self._session_id)
                if capture_session:
                    capture_session.last_heartbeat = datetime.now(timezone.utc)
                    capture_session.packets_captured = (
                        self._sniffer.packet_count if self._sniffer else 0
                    )
                    capture_session.orders_extracted = (
                        self._db_writer.orders_written if self._db_writer else 0
                    )
                    session.commit()
            except Exception as e:
                session.rollback()
                log.debug("heartbeat_error", error=str(e))
            finally:
                session.close()
        except Exception:
            pass

    def _update_session_status(self, status: str) -> None:
        """Update the session status in the database."""
        if not self._session_factory or not self._session_id:
            return

        try:
            session = self._session_factory()
            try:
                capture_session = session.get(CaptureSession, self._session_id)
                if capture_session:
                    capture_session.status = status
                    capture_session.last_heartbeat = datetime.now(timezone.utc)
                    session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()
        except Exception:
            pass


def run_worker(
    worker_config: WorkerConfig,
    db_config: DatabaseConfig,
    capture_config: CaptureConfig,
) -> None:
    """Entry point for worker subprocess."""
    worker = CityWorker(worker_config, db_config, capture_config)
    worker.run()
