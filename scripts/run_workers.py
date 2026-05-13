"""Supervisor: launches and monitors city workers for market data capture."""
from __future__ import annotations

import multiprocessing
import signal
import sys
import time
from pathlib import Path

import click

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from albion_capture.capture.port_detector import detect_and_assign_ports
from albion_capture.core.config import AppConfig, WorkerConfig, load_config
from albion_capture.core.database import Base, create_db_engine
from albion_capture.core.logging import get_logger, setup_logging
from albion_capture.photon.operations import CITY_IDS
from albion_capture.workers.city_worker import run_worker

log = get_logger("supervisor")

# Menu de ciudades (numero -> (nombre, city_id))
CITY_MENU = [
    ("Thetford",     3000),
    ("Fort Sterling",3002),
    ("Lymhurst",     3003),
    ("Martlock",     3004),
    ("Bridgewatch",  3005),
    ("Caerleon",     3008),
    ("Black Market", 3013),
    ("Brecilien",    4002),
]


def pick_city(city_num: int | None) -> tuple[str, int]:
    """Devuelve (nombre, city_id) seleccionando por numero.

    Si city_num es None o invalido, muestra el menu y pregunta.
    """
    if city_num is not None and 1 <= city_num <= len(CITY_MENU):
        return CITY_MENU[city_num - 1]

    click.echo()
    click.echo("  =============================")
    click.echo("   EN QUE CIUDAD ESTAS?")
    click.echo("  =============================")
    for i, (name, _) in enumerate(CITY_MENU, start=1):
        click.echo(f"   {i}. {name}")
    click.echo()
    while True:
        try:
            raw = click.prompt("  Numero", type=int)
            if 1 <= raw <= len(CITY_MENU):
                return CITY_MENU[raw - 1]
        except (click.Abort, KeyboardInterrupt):
            raise
        except Exception:
            pass
        click.echo(f"  Invalido. Debe ser 1-{len(CITY_MENU)}.")


class Supervisor:
    """Manages city worker processes."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._processes: dict[str, multiprocessing.Process] = {}
        self._running = False

    def start(self) -> None:
        """Start all configured workers."""
        self._running = True
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        # Create tables if they don't exist
        self._ensure_tables()

        # Auto-detect ports if needed
        workers_dicts = [w.model_dump() for w in self.config.workers]
        workers_dicts = detect_and_assign_ports(workers_dicts)

        # Update config with detected ports
        worker_configs = [WorkerConfig(**w) for w in workers_dicts]

        # Launch workers
        for wc in worker_configs:
            if not wc.local_port and not wc.local_ports:
                log.warning("skipping_worker_no_port", city=wc.city)
                continue
            self._launch_worker(wc)

        if not self._processes:
            log.error("no_workers_launched")
            return

        log.info("supervisor_running", workers=len(self._processes))

        # Monitor loop
        try:
            while self._running:
                time.sleep(10)
                self._check_workers(worker_configs)
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _launch_worker(self, worker_config: WorkerConfig) -> None:
        """Launch a single worker process."""
        log.info("launching_worker", city=worker_config.city, port=worker_config.local_port)

        proc = multiprocessing.Process(
            target=run_worker,
            args=(worker_config, self.config.database, self.config.capture),
            name=f"worker-{worker_config.city}",
            daemon=True,
        )
        proc.start()
        self._processes[worker_config.city] = proc

    def _check_workers(self, worker_configs: list[WorkerConfig]) -> None:
        """Check worker health and restart dead workers with fresh port detection."""
        for wc in worker_configs:
            if not wc.local_port and not wc.local_ports:
                continue

            proc = self._processes.get(wc.city)
            if proc and not proc.is_alive():
                log.warning("worker_died_restarting", city=wc.city)
                # Re-detect ports in case the game reconnected
                try:
                    fresh = [w.model_dump() for w in self.config.workers]
                    fresh = detect_and_assign_ports(fresh)
                    for fw in fresh:
                        if fw["city"] == wc.city:
                            wc = WorkerConfig(**fw)
                            break
                except Exception as e:
                    log.error("port_redetect_error", error=str(e))
                if wc.local_port or wc.local_ports:
                    self._launch_worker(wc)

    def _ensure_tables(self) -> None:
        """Create database tables if they don't exist."""
        try:
            engine = create_db_engine(self.config.database)
            # Import all models to register them with Base
            import albion_capture.models.capture_session  # noqa
            import albion_capture.models.gold_price  # noqa
            import albion_capture.models.market_order  # noqa
            import albion_capture.models.market_trade  # noqa

            Base.metadata.create_all(engine)
            log.info("database_tables_ensured")
            engine.dispose()
        except Exception as e:
            log.error("database_setup_error", error=str(e))
            raise

    def _signal_handler(self, signum, frame) -> None:
        log.info("supervisor_signal", signal=signum)
        self._running = False

    def _shutdown(self) -> None:
        """Stop all workers gracefully."""
        log.info("supervisor_shutting_down")
        for city, proc in self._processes.items():
            if proc.is_alive():
                log.info("stopping_worker", city=city)
                proc.terminate()
                proc.join(timeout=10)
                if proc.is_alive():
                    proc.kill()
        log.info("supervisor_stopped")


@click.command()
@click.option(
    "--config",
    "-c",
    default=None,
    type=click.Path(exists=True),
    help="Path to settings.yaml config file",
)
@click.option(
    "--log-level",
    "-l",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    help="Log level",
)
@click.option(
    "--city",
    type=int,
    default=None,
    help="Numero de ciudad (1=Thetford, 2=Fort Sterling, 3=Lymhurst, "
         "4=Martlock, 5=Bridgewatch, 6=Caerleon, 7=Black Market, 8=Brecilien). "
         "Si se omite, se pregunta de forma interactiva.",
)
def main(config: str | None, log_level: str, city: int | None) -> None:
    """Albion Online Market Data Capture - Supervisor"""
    setup_logging(log_level)

    try:
        app_config = load_config(config)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("Copy config/settings.example.yaml to config/settings.yaml and configure it.", err=True)
        sys.exit(1)

    # Elegir ciudad (interactiva o por parametro)
    city_name, city_id = pick_city(city)
    click.echo()
    click.echo(f"  >> Ciudad seleccionada: {city_name} (id={city_id})")
    click.echo()

    # Forzar TODOS los workers a esta ciudad
    for wc in app_config.workers:
        wc.city = city_name
        wc.city_id = city_id

    click.echo(f"Starting capture with {len(app_config.workers)} workers...")
    click.echo(f"Cities: {', '.join(w.city for w in app_config.workers)}")
    click.echo(f"Database: {app_config.database.host}:{app_config.database.port}/{app_config.database.name}")
    click.echo()

    supervisor = Supervisor(app_config)
    supervisor.start()


if __name__ == "__main__":
    main()
