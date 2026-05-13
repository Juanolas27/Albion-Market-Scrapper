"""
Background Market Scanner
==========================
Escanea el mercado de Albion sin mover tu raton.
Envia clics directamente a la ventana del juego usando win32gui.

Uso:
  py scripts/bg_scanner.py test          -> Prueba si funciona (clic en desplegable)
  py scripts/bg_scanner.py scan --city 4 -> Escaneo completo en Martlock
  py scripts/bg_scanner.py scan --city 8 -> Escaneo completo en Brecilien

IMPORTANTE: La ventana de Albion puede estar en segundo plano pero NO minimizada.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).parent.parent))

import win32gui
import win32con
import win32api

CALIBRATION_FILE = Path(__file__).parent.parent / "config" / "scanner_calibration.json"

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
# MARKET TREE (copiado de market_scanner.py)
# ===================================================================
MARKET_TREE = [
    [8] * 17,
    [9, 9, 9],
    [9, 9, 9],
    [9, 9, 9],
    [6, 6, 6],
    15,
    2,
    [13, 16, 13],
    [9, 16, 6, 2],
    [6, 5, 5, 5, 5, 5, 1],
    [5, 5, 3, 6, [2, 7, None], 10],
    [[5]*17, [5]*3, [5]*3, [5]*3, [5]*3, 5, 14, 1],
    [[8, 8], [8, 8], [11, 11, 1, 1], [12, 12], [1, 1, 1, 1, 1]],
    [1, 1, 3, 1, 1, 4],
    [1, 12, 1, 1, 1, 1, 1, 1, 1],
    [3, [12, 9, 11, 1, 1], [1, 2, 1, 1], 7,
     [1, 18, 18, 18, 18, 18, 18, 18, 18, 18, 18], [6, 1]],
]

CATEGORY_NAMES = [
    "Armas", "Armadura Pecho", "Armadura Cabeza", "Armadura Pies",
    "Armas Secundarias", "Capas", "Bolsas", "Montura", "Consumible",
    "Equipo Recoleccion", "Fabricacion", "Artefacto", "Agricultura",
    "Mueble", "Cosmetica", "Otros",
]


def generate_all_paths() -> list[list[int]]:
    paths = []

    def _walk(entry, prefix, depth):
        if entry is None:
            paths.append(prefix[:])
        elif isinstance(entry, int):
            for i in range(entry):
                paths.append(prefix + [i + 1])
        elif isinstance(entry, list):
            for i, sub in enumerate(entry):
                _walk(sub, prefix + [i + 1], depth + 1)

    for c1_i, c1_entry in enumerate(MARKET_TREE):
        _walk(c1_entry, [c1_i + 1], 1)

    return paths


# ===================================================================
# WIN32 BACKGROUND INPUT
# ===================================================================

def find_albion_window() -> int:
    """Encuentra la ventana de Albion Online."""
    result = []

    def _enum(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if "albion" in title.lower():
                result.append(hwnd)

    win32gui.EnumWindows(_enum, None)
    return result[0] if result else 0


def _make_lparam(x: int, y: int) -> int:
    """Combina x, y en LPARAM para mensajes de raton."""
    return (y << 16) | (x & 0xFFFF)


def bg_click(hwnd: int, x: int, y: int) -> None:
    """Envia un clic a la ventana hwnd en coordenadas relativas (x, y)."""
    lparam = _make_lparam(x, y)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(0.05)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)


def bg_hover(hwnd: int, x: int, y: int) -> None:
    """Envia un movimiento de raton a la ventana hwnd (hover)."""
    lparam = _make_lparam(x, y)
    win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lparam)


def screen_to_client(hwnd: int, sx: int, sy: int) -> tuple[int, int]:
    """Convierte coordenadas de pantalla a coordenadas relativas a la ventana."""
    cx, cy = win32gui.ScreenToClient(hwnd, (sx, sy))
    return (cx, cy)


# ===================================================================
# CLI
# ===================================================================

@click.group()
def cli():
    """Background Market Scanner — sin mover tu raton."""
    pass


@cli.command()
def test():
    """Prueba si el clic en background funciona.

    Abre el mercado en Albion y deja la ventana visible (no minimizada).
    Este test hara clic en el desplegable del mercado.
    """
    hwnd = find_albion_window()
    if not hwnd:
        click.echo("ERROR: No se encontro la ventana de Albion.")
        click.echo("Asegurate de tener Albion abierto (puede estar en segundo plano, NO minimizado).")
        return

    title = win32gui.GetWindowText(hwnd)
    click.echo(f"Ventana encontrada: '{title}' (hwnd={hwnd})")

    if not CALIBRATION_FILE.exists():
        click.echo("ERROR: Calibracion no encontrada. Ejecuta primero:")
        click.echo("  py scripts/market_scanner.py calibrate")
        return

    with open(CALIBRATION_FILE) as f:
        cal = json.load(f)

    dd_sx, dd_sy = cal["dropdown_x"], cal["dropdown_y"]
    dd_cx, dd_cy = screen_to_client(hwnd, dd_sx, dd_sy)

    click.echo(f"Desplegable: screen=({dd_sx},{dd_sy}) -> client=({dd_cx},{dd_cy})")
    click.echo()
    click.echo("Enviando clic en el desplegable en 3 seg...")
    click.echo("Mira la ventana de Albion (sin tocar tu raton).")
    time.sleep(3)

    bg_click(hwnd, dd_cx, dd_cy)

    click.echo()
    click.echo("Clic enviado. Si el desplegable se abrio, FUNCIONA!")
    click.echo("Si no paso nada, Albion no acepta background input :(")


@cli.command()
@click.option("--city", type=int, required=True,
              help="1=Thetford, 2=Fort Sterling, 3=Lymhurst, 4=Martlock, "
                   "5=Bridgewatch, 6=Caerleon, 7=Black Market, 8=Brecilien")
@click.option("--delay", "-d", default=0.8, help="Seg espera tras clic en item")
@click.option("--hover-delay", default=0.25, help="Seg espera tras hover")
@click.option("--tiers", default="4,5,6,7,8", help="Tiers (1-8) separados por coma")
@click.option("--enchants", default="0,1,2,3,4", help="Enchants (0-4)")
@click.option("--qualities", default="1,2,3,4,5", help="Calidades (1-5)")
@click.option("--variant-delay", default=0.4, help="Seg entre variantes")
@click.option("--start-from", default=0, help="Saltar N items")
@click.option("--loop", "loop_", is_flag=True, help="Repetir infinitamente")
@click.option("--loop-pause", default=60, help="Seg entre ciclos de loop")
def scan(city, delay, hover_delay, tiers, enchants, qualities,
         variant_delay, start_from, loop_, loop_pause):
    """Escaneo completo en background."""
    # Validar ciudad
    city_map = {n: (name, cid) for n, name, cid in CITIES}
    if city not in city_map:
        click.echo(f"ERROR: Ciudad invalida. Usa 1-{len(CITIES)}.")
        return
    city_name, city_id = city_map[city]

    # Ventana
    hwnd = find_albion_window()
    if not hwnd:
        click.echo("ERROR: Ventana de Albion no encontrada.")
        return
    click.echo(f"Ventana: '{win32gui.GetWindowText(hwnd)}'")

    # Calibracion
    if not CALIBRATION_FILE.exists():
        click.echo("ERROR: Ejecuta primero: py scripts/market_scanner.py calibrate")
        return
    with open(CALIBRATION_FILE) as f:
        cal = json.load(f)

    # Posiciones (convertir screen -> client)
    col1_positions = cal.get("col1_positions", [])
    if not col1_positions or len(col1_positions) < 17:
        click.echo("ERROR: Calibracion incompleta. Recalibra.")
        return

    def s2c(sx, sy):
        return screen_to_client(hwnd, sx, sy)

    dd_c = s2c(cal["dropdown_x"], cal["dropdown_y"])
    col1_pos_c = [s2c(p[0], p[1]) for p in col1_positions]

    col_x_c = {
        1: col1_pos_c[0][0],
        2: s2c(cal["col2_x"], 0)[0],
        3: s2c(cal["col3_x"], 0)[0],
        4: s2c(cal["col4_x"], 0)[0],
    }
    col_h = {1: cal["col1_h"], 2: cal["col2_h"], 3: cal["col3_h"], 4: cal["col4_h"]}
    col_offset_y = {
        2: cal.get("col2_offset_y", 0),
        3: cal.get("col3_offset_y", 0),
        4: cal.get("col4_offset_y", 0),
    }

    # Tiers/enchants/qualities
    tier_positions = cal.get("tier_positions") or []
    ench_positions = cal.get("ench_positions") or []
    qual_positions = cal.get("qual_positions") or []
    tier_dd = cal.get("tier_dropdown")
    ench_dd = cal.get("ench_dropdown")
    qual_dd = cal.get("qual_dropdown")

    tier_pos_c = [s2c(p[0], p[1]) for p in tier_positions] if tier_positions else []
    ench_pos_c = [s2c(p[0], p[1]) for p in ench_positions] if ench_positions else []
    qual_pos_c = [s2c(p[0], p[1]) for p in qual_positions] if qual_positions else []
    tier_dd_c = s2c(tier_dd[0], tier_dd[1]) if tier_dd else None
    ench_dd_c = s2c(ench_dd[0], ench_dd[1]) if ench_dd else None
    qual_dd_c = s2c(qual_dd[0], qual_dd[1]) if qual_dd else None

    tier_list = [int(t) for t in tiers.split(",") if t.strip()] if tiers else []
    ench_list = [int(e) for e in enchants.split(",") if e.strip()] if enchants else []
    qual_list = [int(q) for q in qualities.split(",") if q.strip()] if qualities else []
    tier_list = [t for t in tier_list if 1 <= t <= 8 and tier_pos_c and tier_dd_c]
    ench_list = [e for e in ench_list if 0 <= e <= 4 and ench_pos_c and ench_dd_c]
    qual_list = [q for q in qual_list if 1 <= q <= 5 and qual_pos_c and qual_dd_c]
    if not tier_list: tier_list = [None]
    if not ench_list: ench_list = [None]
    if not qual_list: qual_list = [None]
    variants = len(tier_list) * len(ench_list) * len(qual_list)

    all_paths = generate_all_paths()
    total = len(all_paths)

    click.echo()
    click.echo("=" * 60)
    click.echo(f"  BACKGROUND SCANNER — {city_name}")
    click.echo("=" * 60)
    click.echo(f"  Items: {total} | Variantes/item: {variants}")
    click.echo(f"  Total clics: {total * variants}")
    per_item = delay + hover_delay * 3 + 0.3 + (variants - 1) * (variant_delay + 0.3)
    click.echo(f"  Tiempo estimado: ~{total * per_item / 60:.0f} min")
    if loop_:
        click.echo(f"  Modo LOOP: repite cada {loop_pause}s")
    click.echo()

    cycle = 0
    while True:
        cycle += 1
        paths = all_paths[start_from:] if start_from > 0 and cycle == 1 else all_paths
        scanned = 0
        last_cat = -1

        click.echo(f"  --- Ciclo {cycle} | {len(paths)} items ---")

        for path in paths:
            cat_idx = path[0] - 1
            if cat_idx != last_cat:
                last_cat = cat_idx
                name = CATEGORY_NAMES[cat_idx] if cat_idx < len(CATEGORY_NAMES) else f"Cat {cat_idx+1}"
                click.echo(f"  [{scanned}/{len(paths)}] {name}")

            # 1. Clic desplegable
            bg_click(hwnd, dd_c[0], dd_c[1])
            time.sleep(0.3)

            # 2. Navegar menu
            parent_y = 0
            for level_idx, row in enumerate(path):
                col_num = level_idx + 1
                ch = col_h[col_num]

                if col_num == 1:
                    if row < len(col1_pos_c):
                        cx, target_y = col1_pos_c[row]
                    else:
                        cx = col_x_c[1]
                        target_y = col1_pos_c[0][1] + row * ch
                else:
                    cx = col_x_c[col_num]
                    offset = col_offset_y.get(col_num, 0)
                    # Convertir offset de screen a client (solo Y diff, no absoluto)
                    target_y = parent_y + offset + row * ch

                is_last = (level_idx == len(path) - 1)

                if is_last:
                    bg_click(hwnd, cx, target_y)
                else:
                    bg_hover(hwnd, cx, target_y)
                    time.sleep(hover_delay)
                    parent_y = target_y

            time.sleep(delay)

            # 3. Variantes (tier x ench x quality)
            def _bg_select(dd_pos, options, idx):
                bg_click(hwnd, dd_pos[0], dd_pos[1])
                time.sleep(0.25)
                bg_click(hwnd, options[idx][0], options[idx][1])
                time.sleep(variant_delay)

            has_variants = any(t is not None for t in tier_list) or \
                           any(e is not None for e in ench_list) or \
                           any(q is not None for q in qual_list)

            if has_variants:
                for tier in tier_list:
                    if tier is not None:
                        _bg_select(tier_dd_c, tier_pos_c, tier - 1)
                    for ench in ench_list:
                        if ench is not None:
                            _bg_select(ench_dd_c, ench_pos_c, ench)
                        for qual in qual_list:
                            if qual is not None:
                                _bg_select(qual_dd_c, qual_pos_c, qual - 1)

            scanned += 1
            if scanned % 50 == 0:
                click.echo(f"  [{scanned}/{len(paths)}] escaneados...")

        click.echo(f"  Ciclo {cycle} completado: {scanned} items")

        if not loop_:
            break

        click.echo(f"  Siguiente ciclo en {loop_pause}s...")
        time.sleep(loop_pause)

    click.echo()
    click.echo("  SCAN COMPLETADO")


if __name__ == "__main__":
    cli()
