"""
Lanzador de workers en background
==================================
Arranca workers de captura para una o varias ciudades.
Corre en background sin necesitar pantalla — captura todo lo que
hagas en el mercado mientras juegas.

Uso:
  py scripts/run_background.py                   -> pregunta ciudad
  py scripts/run_background.py --city 4          -> Martlock directo
  py scripts/run_background.py --city 4 --city 8 -> Martlock + Brecilien
  py scripts/run_background.py --all             -> todas las ciudades

Para que capture datos: ten el juego abierto y navega el mercado normalmente.
"""
from __future__ import annotations

import multiprocessing
import signal
import sys
import time
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).parent.parent))

from albion_capture.capture.port_detector import detect_and_assign_ports
from albion_capture.core.config import WorkerConfig, load_config
from albion_capture.core.database import Base, create_db_engine
from albion_capture.core.logging import get_logger, setup_logging
from albion_capture.workers.city_worker import run_worker

log = get_logger("background")

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


def pick_cities_interactive() -> list[tuple[str, int]]:
    click.echo()
    click.echo("  =============================")
    click.echo("   CIUDADES A CAPTURAR")
    click.echo("  =============================")
    for num, name, _ in CITIES:
        click.echo(f"   {num}. {name}")
    click.echo(f"   0. Todas")
    click.echo()
    raw = click.prompt("  Numeros separados por comas (ej: 4,8)", type=str)

    if raw.strip() == "0":
        return [(name, cid) for _, name, cid in CITIES]

    selected = []
    for s in raw.split(","):
        s = s.strip()
        if s.isdigit():
            n = int(s)
            for num, name, cid in CITIES:
                if num == n:
                    selected.append((name, cid))
    return selected


@click.command()
@click.option("--city", multiple=True, type=int,
              help="Numero de ciudad (repetible). 1=Thetford..8=Brecilien.")
@click.option("--all-cities", "all_", is_flag=True, help="Todas las ciudades.")
@click.option("--log-level", "-l", default="INFO",
              type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]))
def main(city: tuple[int, ...], all_: bool, log_level: str):
    """Lanza workers de captura en background."""
    setup_logging(log_level)

    app_config = load_config()

    # Determinar ciudades
    if all_:
        selected = [(name, cid) for _, name, cid in CITIES]
    elif city:
        city_map = {num: (name, cid) for num, name, cid in CITIES}
        selected = [city_map[c] for c in city if c in city_map]
    else:
        selected = pick_cities_interactive()

    if not selected:
        click.echo("No se selecciono ninguna ciudad.")
        return

    # Crear tablas
    engine = create_db_engine(app_config.database)
    import albion_capture.models.capture_session  # noqa
    import albion_capture.models.gold_price  # noqa
    import albion_capture.models.market_order  # noqa
    import albion_capture.models.market_trade  # noqa
    Base.metadata.create_all(engine)
    engine.dispose()
    log.info("database_tables_ensured")

    # Detectar puertos
    workers_raw = [{"city": name, "city_id": cid} for name, cid in selected]
    workers_raw = detect_and_assign_ports(workers_raw)

    click.echo()
    click.echo("=" * 60)
    click.echo("  CAPTURA EN BACKGROUND")
    click.echo("=" * 60)
    click.echo()
    click.echo(f"  BD: {app_config.database.host}:{app_config.database.port}/{app_config.database.name}")
    click.echo()

    # Lanzar workers
    processes: dict[str, multiprocessing.Process] = {}
    for wd in workers_raw:
        wc = WorkerConfig(**wd)
        if not wc.local_port and not wc.local_ports:
            click.echo(f"  {wc.city}: SIN PUERTOS (juego no detectado)")
            continue
        ports = wc.local_ports or [wc.local_port]
        click.echo(f"  {wc.city}: capturando en puertos {ports}")
        proc = multiprocessing.Process(
            target=run_worker,
            args=(wc, app_config.database, app_config.capture),
            name=f"worker-{wc.city}",
            daemon=True,
        )
        proc.start()
        processes[wc.city] = proc

    if not processes:
        click.echo("\n  No se lanzo ningun worker. Asegurate de tener Albion abierto.")
        return

    click.echo()
    click.echo(f"  {len(processes)} worker(s) corriendo. Ctrl+C para detener.")
    click.echo("  Juega normalmente — al abrir el mercado se capturan los datos.")
    click.echo()

    # Mantener vivo
    running = True

    def _stop(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        while running:
            time.sleep(5)
            # Comprobar workers vivos
            for city, proc in list(processes.items()):
                if not proc.is_alive():
                    log.warning("worker_died", city=city)
                    del processes[city]
            if not processes:
                click.echo("  Todos los workers han muerto.")
                break
    except KeyboardInterrupt:
        pass
    finally:
        click.echo("\n  Deteniendo workers...")
        for city, proc in processes.items():
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)
        click.echo("  Listo.")


if __name__ == "__main__":
    main()
