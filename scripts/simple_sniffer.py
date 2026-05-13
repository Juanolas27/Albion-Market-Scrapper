"""
Albion Market Sniffer (standalone)
====================================
Sniffer ligero que captura datos de mercado de Albion Online y los guarda
en SQLite local. Sin Docker, sin PostgreSQL, sin configuracion.

Uso:
  py scripts/simple_sniffer.py              -> pregunta ciudad
  py scripts/simple_sniffer.py --city 4     -> Martlock directo
  py scripts/simple_sniffer.py --city 8     -> Brecilien

Cualquier cosa que navegues en el mercado mientras corre, se captura.
La BD se guarda en: <proyecto>/data/market.db
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).parent.parent))

from albion_capture.capture.port_detector import find_albion_clients
from albion_capture.capture.sniffer import AlbionSniffer
from albion_capture.core.logging import get_logger, setup_logging
from albion_capture.photon.decoder import PhotonDecoder
from albion_capture.photon.market_parser import (
    get_albion_op_code,
    parse_market_history,
    parse_market_orders,
)
from albion_capture.photon.operations import CITY_NAMES, OperationCodes

log = get_logger("sniffer")

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"

CITIES = [
    (1, "Thetford",      3000),
    (2, "Fort Sterling", 3002),
    (3, "Lymhurst",      3003),
    (4, "Martlock",      3004),
    (5, "Bridgewatch",   3005),
    (6, "Caerleon",      3008),
    (7, "Black Market",  3013),
    (8, "Brecilien",     4002),
]


# ===================================================================
# SQLITE STORAGE
# ===================================================================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS market_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER UNIQUE NOT NULL,
    item_albion_id TEXT NOT NULL,
    city_id INTEGER NOT NULL,
    quality_level INTEGER NOT NULL DEFAULT 1,
    enchantment_level INTEGER NOT NULL DEFAULT 0,
    unit_price_silver INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    auction_type TEXT NOT NULL,
    tier INTEGER DEFAULT 0,
    expires_at TEXT,
    captured_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    uploaded INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_orders_item_city ON market_orders(item_albion_id, city_id);
CREATE INDEX IF NOT EXISTS ix_orders_captured ON market_orders(captured_at);
CREATE INDEX IF NOT EXISTS ix_orders_auction ON market_orders(auction_type);
CREATE INDEX IF NOT EXISTS ix_orders_uploaded ON market_orders(uploaded);

CREATE TABLE IF NOT EXISTS market_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_albion_id TEXT NOT NULL,
    city_id INTEGER NOT NULL,
    quality_level INTEGER NOT NULL,
    timescale INTEGER NOT NULL,
    item_amount INTEGER NOT NULL,
    silver_amount INTEGER NOT NULL,
    avg_price INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    captured_at TEXT DEFAULT CURRENT_TIMESTAMP,
    uploaded INTEGER NOT NULL DEFAULT 0,
    UNIQUE(item_albion_id, city_id, quality_level, timescale, timestamp)
);

CREATE INDEX IF NOT EXISTS ix_history_item_city ON market_history(item_albion_id, city_id);
CREATE INDEX IF NOT EXISTS ix_history_uploaded ON market_history(uploaded);
"""


class SQLiteWriter:
    """Escribe ordenes/historial a SQLite por lotes."""

    def __init__(self, db_path: Path, batch_size: int = 50, flush_interval: float = 3.0):
        self.db_path = db_path
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)

        # 1) Migracion PREVIA: si la BD ya existia sin la columna "uploaded",
        #    la anadimos ANTES de ejecutar el schema completo (que crea
        #    indices sobre esa columna).
        for tbl in ("market_orders", "market_history"):
            try:
                cols = [r[1] for r in self._conn.execute(f"PRAGMA table_info({tbl})")]
            except sqlite3.OperationalError:
                cols = []  # tabla aun no existe; la creara el schema
            if cols and "uploaded" not in cols:
                self._conn.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN uploaded INTEGER NOT NULL DEFAULT 0"
                )
        self._conn.commit()

        # 2) Schema (CREATE TABLE/INDEX IF NOT EXISTS).
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

        self._orders_buf: list[tuple] = []
        self._history_buf: list[tuple] = []
        self._lock = threading.Lock()
        self._last_flush = time.monotonic()

        self.orders_written = 0
        self.history_written = 0

        self._running = True
        self._flusher = threading.Thread(target=self._flush_loop, daemon=True)
        self._flusher.start()

    def add_orders(self, orders: list) -> None:
        if not orders:
            return
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for o in orders:
            rows.append((
                o.order_id, o.item_albion_id, o.city_id,
                o.quality_level, o.enchantment_level,
                o.unit_price_silver, o.amount, o.auction_type,
                o.tier,
                o.expires_at.isoformat() if o.expires_at else None,
                now, now,
            ))
        with self._lock:
            self._orders_buf.extend(rows)
            if len(self._orders_buf) >= self.batch_size:
                self._flush()

    def add_history(self, histories: list) -> None:
        if not histories:
            return
        rows = []
        for h in histories:
            rows.append((
                h.item_albion_id, h.city_id, h.quality_level,
                h.timescale, h.item_amount, h.silver_amount,
                h.avg_price, h.timestamp.isoformat(),
            ))
        with self._lock:
            self._history_buf.extend(rows)
            if len(self._history_buf) >= self.batch_size:
                self._flush()

    def _flush(self) -> None:
        if self._orders_buf:
            try:
                self._conn.executemany(
                    """INSERT INTO market_orders (
                        order_id, item_albion_id, city_id,
                        quality_level, enchantment_level,
                        unit_price_silver, amount, auction_type, tier,
                        expires_at, captured_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(order_id) DO UPDATE SET
                        unit_price_silver=excluded.unit_price_silver,
                        amount=excluded.amount,
                        updated_at=excluded.updated_at,
                        uploaded=0""",
                    self._orders_buf,
                )
                self._conn.commit()
                self.orders_written += len(self._orders_buf)
                self._orders_buf.clear()
            except Exception as e:
                log.error("orders_flush_error", error=str(e))

        if self._history_buf:
            try:
                self._conn.executemany(
                    """INSERT OR IGNORE INTO market_history (
                        item_albion_id, city_id, quality_level, timescale,
                        item_amount, silver_amount, avg_price, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    self._history_buf,
                )
                self._conn.commit()
                self.history_written += len(self._history_buf)
                self._history_buf.clear()
            except Exception as e:
                log.error("history_flush_error", error=str(e))

        self._last_flush = time.monotonic()

    def _flush_loop(self) -> None:
        while self._running:
            time.sleep(self.flush_interval)
            now = time.monotonic()
            if now - self._last_flush >= self.flush_interval:
                with self._lock:
                    self._flush()

    def close(self) -> None:
        self._running = False
        with self._lock:
            self._flush()
        self._conn.close()


# ===================================================================
# SERVER UPLOADER (opcional)
# ===================================================================

class ServerUploader:
    """Lee filas no subidas de SQLite y las envia al servidor central.

    Usa SQLite como buffer offline: si el servidor cae, los datos se
    acumulan localmente y se reintenta con backoff exponencial.
    """

    BATCH = 500

    def __init__(self, db_path: Path, server_url: str, api_key: str, interval: float = 10.0):
        self.db_path = db_path
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.interval = interval
        # Fingerprint: primero env (lo pone el launcher). Si no, lo calculamos.
        self.device_header = os.environ.get("ALBION_DEVICE_INFO")
        if not self.device_header:
            try:
                sys.path.insert(0, str(Path(__file__).parent.parent / "client"))
                from fingerprint import encode_header  # type: ignore
                self.device_header = encode_header()
            except Exception:
                self.device_header = ""

        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._backoff = interval

        self.orders_sent = 0
        self.history_sent = 0
        self.failures = 0
        self.last_error: str | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                sent_o = self._upload_orders()
                sent_h = self._upload_history()
                if sent_o or sent_h:
                    # exito: reset backoff
                    self._backoff = self.interval
                time.sleep(self.interval if self._backoff <= self.interval else self._backoff)
            except Exception as e:
                self.failures += 1
                self.last_error = str(e)
                self._backoff = min(self._backoff * 2, 300.0)
                time.sleep(self._backoff)

    def _fetch_unsent_orders(self) -> list[tuple]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, order_id, item_albion_id, city_id, quality_level,
                          enchantment_level, unit_price_silver, amount, auction_type,
                          tier, expires_at
                   FROM market_orders WHERE uploaded = 0
                   ORDER BY id LIMIT ?""",
                (self.BATCH,),
            ).fetchall()
        return rows

    def _fetch_unsent_history(self) -> list[tuple]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, item_albion_id, city_id, quality_level, timescale,
                          item_amount, silver_amount, avg_price, timestamp
                   FROM market_history WHERE uploaded = 0
                   ORDER BY id LIMIT ?""",
                (self.BATCH,),
            ).fetchall()
        return rows

    def _upload_orders(self) -> int:
        rows = self._fetch_unsent_orders()
        if not rows:
            return 0
        payload = [{
            "order_id": r[1],
            "item_albion_id": r[2],
            "city_id": r[3],
            "quality_level": r[4],
            "enchantment_level": r[5],
            "unit_price_silver": r[6],
            "amount": r[7],
            "auction_type": r[8],
            "tier": r[9] or 0,
            "expires_at": r[10],
        } for r in rows]
        self._post("/api/v1/orders", payload)
        ids = [r[0] for r in rows]
        with self._lock:
            qs = ",".join("?" * len(ids))
            self._conn.execute(
                f"UPDATE market_orders SET uploaded = 1 WHERE id IN ({qs})", ids,
            )
            self._conn.commit()
        self.orders_sent += len(ids)
        return len(ids)

    def _upload_history(self) -> int:
        rows = self._fetch_unsent_history()
        if not rows:
            return 0
        payload = [{
            "item_albion_id": r[1],
            "city_id": r[2],
            "quality_level": r[3],
            "timescale": r[4],
            "item_amount": r[5],
            "silver_amount": r[6],
            "avg_price": r[7],
            "timestamp": r[8],
        } for r in rows]
        self._post("/api/v1/history", payload)
        ids = [r[0] for r in rows]
        with self._lock:
            qs = ",".join("?" * len(ids))
            self._conn.execute(
                f"UPDATE market_history SET uploaded = 1 WHERE id IN ({qs})", ids,
            )
            self._conn.commit()
        self.history_sent += len(ids)
        return len(ids)

    def _post(self, path: str, payload: list) -> None:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "User-Agent": "albion-sniffer/1.0",
        }
        if self.device_header:
            headers["X-Device-Info"] = self.device_header
        req = urllib.request.Request(
            self.server_url + path,
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            # 401/403 = key invalida/desactivada -> no reintentar en bucle corto
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")


# ===================================================================
# MAIN SNIFFER
# ===================================================================

class MarketSniffer:
    """Sniffer standalone que captura datos de mercado."""

    def __init__(self, city_name: str, city_id: int, db_path: Path,
                 server_url: str | None = None, api_key: str | None = None):
        self.city_name = city_name
        self.city_id = city_id
        self.db_path = db_path
        self.server_url = server_url
        self.api_key = api_key

        self._sniffer: AlbionSniffer | None = None
        self._decoder: PhotonDecoder | None = None
        self._writer: SQLiteWriter | None = None
        self._uploader: ServerUploader | None = None
        self._running = False

        self._stats_start = time.monotonic()
        self._op_counts: dict[int, int] = {}

    def start(self, ports: list[int]) -> None:
        """Arranca la captura."""
        self._writer = SQLiteWriter(self.db_path)
        if self.server_url and self.api_key:
            self._uploader = ServerUploader(self.db_path, self.server_url, self.api_key)
            self._uploader.start()
        self._decoder = PhotonDecoder(
            on_response=self._on_response,
            on_event=lambda e, p: None,
        )
        self._sniffer = AlbionSniffer(
            local_ports=ports,
            callback=lambda data, *_args: self._decoder.handle_payload(data),
        )
        self._sniffer.start()
        self._running = True

        # Thread de stats
        threading.Thread(target=self._stats_loop, daemon=True).start()

        log.info("sniffer_started", city=self.city_name, ports=ports, db=str(self.db_path))

    def stop(self) -> None:
        self._running = False
        if self._sniffer:
            self._sniffer.stop()
        if self._uploader:
            self._uploader.stop()
        if self._writer:
            self._writer.close()

    def _on_response(self, op_code: int, params: dict) -> None:
        albion_op = get_albion_op_code(params) or op_code
        # Debug: contabiliza ops vistas
        self._op_counts[albion_op] = self._op_counts.get(albion_op, 0) + 1

        if albion_op in (OperationCodes.AUCTION_GET_OFFERS, OperationCodes.AUCTION_GET_REQUESTS):
            orders = parse_market_orders(params, self.city_id)
            if orders and self._writer:
                self._writer.add_orders(orders)

        elif albion_op == OperationCodes.AUCTION_GET_ITEM_AVERAGE_STATS:
            histories = parse_market_history(params, self.city_id)
            if histories and self._writer:
                self._writer.add_history(histories)

    def _stats_loop(self) -> None:
        while self._running:
            time.sleep(15)
            if not self._running:
                break
            elapsed = time.monotonic() - self._stats_start
            packets = self._sniffer.packet_count if self._sniffer else 0
            orders = self._writer.orders_written if self._writer else 0
            history = self._writer.history_written if self._writer else 0
            ds = self._decoder.stats if self._decoder else {}
            click.echo(
                f"  [{int(elapsed)}s] pkts={packets} resp={ds.get('responses',0)} "
                f"evt={ds.get('events',0)} frag={ds.get('fragments_reassembled',0)} "
                f"enc={ds.get('encrypted',0)} err={ds.get('errors',0)} "
                f"orders={orders} history={history} ciudad={self.city_name}"
            )
            if self._uploader:
                u = self._uploader
                extra = f" fails={u.failures}" if u.failures else ""
                click.echo(f"        upload: orders={u.orders_sent} history={u.history_sent}{extra}")
                if u.last_error and u.failures:
                    click.echo(f"        last_err: {u.last_error[:120]}")
            # Top 5 ops vistas
            if self._op_counts:
                top = sorted(self._op_counts.items(), key=lambda x: -x[1])[:5]
                click.echo(f"        ops: {top}")
            # Msg types vistos (2=req, 3=resp, 4=evt, >=0x80=encrypted)
            if self._decoder and self._decoder._msg_type_counts:
                mt = sorted(self._decoder._msg_type_counts.items(), key=lambda x: -x[1])[:5]
                click.echo(f"        msg_types: {mt}")
            if self._decoder and hasattr(self._decoder, "_first_errors"):
                for mt, err_info in self._decoder._first_errors.items():
                    click.echo(f"        err mt={mt}: {err_info}")


# ===================================================================
# CITY PICKER
# ===================================================================

def pick_city(city_num: int | None) -> tuple[str, int]:
    if city_num is not None:
        for num, name, cid in CITIES:
            if num == city_num:
                return (name, cid)

    click.echo()
    click.echo("  ================================")
    click.echo("   EN QUE CIUDAD ESTAS?")
    click.echo("  ================================")
    for num, name, _ in CITIES:
        click.echo(f"   {num}. {name}")
    click.echo()
    while True:
        try:
            raw = click.prompt("  Numero", type=int)
            for num, name, cid in CITIES:
                if num == raw:
                    return (name, cid)
            click.echo(f"  Invalido. Usa 1-{len(CITIES)}.")
        except (click.Abort, KeyboardInterrupt):
            sys.exit(0)


# ===================================================================
# CLI
# ===================================================================

@click.command()
@click.option("--city", type=int, default=None,
              help="Numero de ciudad (1=Thetford..8=Brecilien). Si se omite, se pregunta.")
@click.option("--db", type=click.Path(), default=None,
              help="Ruta a la BD SQLite (default: data/market.db)")
@click.option("--server", "server_url", default=None,
              help="URL del servidor central (ej: https://albion.midominio.com). Si se omite, solo guarda en SQLite local.")
@click.option("--api-key", "api_key", default=None,
              help="API key para el servidor (env: ALBION_API_KEY).")
@click.option("--log-level", "-l", default="INFO",
              type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]))
def main(city: int | None, db: str | None, server_url: str | None, api_key: str | None, log_level: str):
    """Sniffer ligero de mercado de Albion Online (SQLite + upload opcional)."""
    import os
    setup_logging(log_level)

    # API key desde env si no se paso por flag
    if not api_key:
        api_key = os.environ.get("ALBION_API_KEY")
    if not server_url:
        server_url = os.environ.get("ALBION_SERVER_URL")

    # 1. Elegir ciudad
    city_name, city_id = pick_city(city)

    # 2. Detectar Albion
    click.echo()
    click.echo("  Buscando Albion Online...")
    clients = find_albion_clients()
    if not clients:
        click.echo("  ERROR: No se encontro Albion. Abrelo e intenta de nuevo.")
        return

    client = clients[0]
    ports = client.local_ports
    click.echo(f"  Albion detectado (pid={client.pid}, puertos={ports})")

    # 3. BD path
    db_path = Path(db) if db else DB_PATH

    # 4. Banner
    click.echo()
    click.echo("=" * 60)
    click.echo(f"  ALBION MARKET SNIFFER")
    click.echo("=" * 60)
    click.echo(f"  Ciudad:   {city_name} (id={city_id})")
    click.echo(f"  BD:       {db_path}")
    click.echo(f"  Puertos:  {ports}")
    if server_url and api_key:
        click.echo(f"  Servidor: {server_url}  (upload activo)")
    elif server_url or api_key:
        click.echo("  Servidor: CONFIG INCOMPLETA (necesitas --server Y --api-key)")
        server_url = api_key = None
    else:
        click.echo("  Servidor: (solo local, sin upload)")
    click.echo("=" * 60)
    click.echo()
    click.echo("  Arrancando captura...")
    click.echo("  Navega por el mercado en Albion para capturar datos.")
    click.echo("  Ctrl+C para detener.")
    click.echo()

    # 5. Sniffer
    sniffer = MarketSniffer(city_name, city_id, db_path,
                             server_url=server_url, api_key=api_key)
    sniffer.start(ports)

    # 6. Mantener vivo
    def _stop(sig, frame):
        click.echo("\n  Deteniendo...")
        sniffer.stop()
        click.echo("  Listo.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        _stop(None, None)


if __name__ == "__main__":
    main()
