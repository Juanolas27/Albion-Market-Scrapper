"""
Albion Market Scanner
=====================
Navega automaticamente por TODAS las categorias del mercado de Albion Online
usando la estructura exacta de menus hover + clic.

Flujo por cada item:
  1. Clic desplegable         -> abre menu
  2. Hover categoria (col1)   -> aparece col2
  3. Hover subcategoria (col2) -> aparece col3
  4. Clic item (ultima col)   -> carga ordenes, menu se cierra
  5. Repetir

Uso:
  python scripts/market_scanner.py calibrate
  python scripts/market_scanner.py scan
  python scripts/market_scanner.py prices

Seguridad: esquina SUPERIOR-IZQUIERDA = ABORTAR
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
except ImportError:
    print("ERROR: pyautogui no instalado. Ejecuta: py -m pip install pyautogui")
    sys.exit(1)

CALIBRATION_FILE = Path(__file__).parent.parent / "config" / "scanner_calibration.json"
SILVER_DIVISOR = 10000


# ===================================================================
# ESTRUCTURA DEL MERCADO DE ALBION
# ===================================================================
# Formato:
#   int N      = N items hoja (sin Todo). Se clickean directamente.
#   list [...]  = subcategorias. Cada entrada es recursiva.
#   None       = este item es hoja (se clickea).
#
# Nivel 0 = col1 categorias (sin Todo)
# Nivel 1 = col2 subcategorias (sin Todo)
# Nivel 2 = col3 items (sin Todo)
# Nivel 3 = col4 sub-items (sin Todo)
#
# Ejemplo: [8, 8] = 2 subcats, cada una con 8 items hoja
# Ejemplo: [[5]*3, 14] = 2 subcats: primera tiene 3 items con 5 sub-items
#                         cada uno, segunda tiene 14 items hoja

MARKET_TREE = [
    # 1. Armas: 17 tipos de arma, cada uno con 8 items
    [8] * 17,

    # 2. Armadura de Pecho: 3 subcats, cada una 9 items
    [9, 9, 9],

    # 3. Armadura de Cabeza: 3 subcats, cada una 9 items
    [9, 9, 9],

    # 4. Armadura de Pies: 3 subcats, cada una 9 items
    [9, 9, 9],

    # 5. Armas Secundarias: 3 subcats, cada una 6 items
    [6, 6, 6],

    # 6. Capas: 15 items hoja directos
    15,

    # 7. Bolsas: 2 items hoja directos
    2,

    # 8. Montura: 3 subcats con 13/16/13 items
    [13, 16, 13],

    # 9. Consumible: 4 subcats con 9/16/6/2 items
    [9, 16, 6, 2],

    # 10. Equipo de Recoleccion: 7 subcats
    [6, 5, 5, 5, 5, 5, 1],

    # 11. Fabricacion: 6 subcats
    #     sub5 tiene 3 items: primeros 2 con col4 (2 y 7), tercero es hoja
    [5, 5, 3, 6, [2, 7, None], 10],

    # 12. Artefacto: 8 subcats
    #     sub1: 17 col3 items, cada uno con 5 col4 items
    #     sub2-5: 3 col3 items, cada uno con 5 col4 items
    #     sub6: 5 items hoja
    #     sub7: 14 items hoja
    #     sub8: 1 item hoja (pendiente confirmar)
    [
        [5] * 17,   # sub1
        [5] * 3,    # sub2
        [5] * 3,    # sub3
        [5] * 3,    # sub4
        [5] * 3,    # sub5
        5,           # sub6: 5 hojas
        14,          # sub7: 14 hojas
        1,           # sub8: 1 hoja (TODO confirmar)
    ],

    # 13. Agricultura: 5 subcats
    [
        [8, 8],              # sub1: 2 col3 con 8 col4
        [8, 8],              # sub2: 2 col3 con 8 col4
        [11, 11, 1, 1],      # sub3: 4 col3 con col4
        [12, 12],            # sub4: 2 col3 con 12 col4
        [1, 1, 1, 1, 1],     # sub5: 5 col3 con 1 col4
    ],

    # 14. Mueble: 6 subcats con 1/1/3/1/1/4 items
    [1, 1, 3, 1, 1, 4],

    # 15. Cosmetica: 9 subcats con 1/12/1/1/1/1/1/1/1 items
    [1, 12, 1, 1, 1, 1, 1, 1, 1],

    # 16. Otros: 6 subcats
    [
        3,                                                  # sub1: 3 hojas
        [12, 9, 11, 1, 1],                                  # sub2: 5 col3 con col4
        [1, 2, 1, 1],                                       # sub3: 4 col3 con col4
        7,                                                  # sub4: 7 hojas
        [1, 18, 18, 18, 18, 18, 18, 18, 18, 18, 18],        # sub5: 11 col3 con col4
        [6, 1],                                             # sub6: 2 col3 con col4
    ],
]

CATEGORY_NAMES = [
    "Armas", "Armadura Pecho", "Armadura Cabeza", "Armadura Pies",
    "Armas Secundarias", "Capas", "Bolsas", "Montura", "Consumible",
    "Equipo Recoleccion", "Fabricacion", "Artefacto", "Agricultura",
    "Mueble", "Cosmetica", "Otros",
]


# ===================================================================
# GENERADOR DE RUTAS
# ===================================================================

def generate_all_paths() -> list[list[int]]:
    """Genera todas las rutas de navegacion desde el arbol del mercado.

    Cada ruta es una lista de indices de fila (saltando Todo, indice 0):
      [col1_row, col2_row]                    -> hover col1, click col2
      [col1_row, col2_row, col3_row]          -> hover col1+col2, click col3
      [col1_row, col2_row, col3_row, col4_row] -> hover col1+col2+col3, click col4
    """
    paths = []

    def _walk(entry, prefix: list[int], depth: int):
        if entry is None:
            # Este nodo es hoja -> la ruta termina aqui
            paths.append(prefix[:])
        elif isinstance(entry, int):
            # N items hoja en el siguiente nivel
            for i in range(entry):
                paths.append(prefix + [i + 1])  # +1 para saltar Todo
        elif isinstance(entry, list):
            # Lista de subcategorias
            for i, sub in enumerate(entry):
                row = i + 1  # +1 para saltar Todo
                _walk(sub, prefix + [row], depth + 1)

    for c1_i, c1_entry in enumerate(MARKET_TREE):
        c1_row = c1_i + 1  # +1 para saltar Todo en col1
        _walk(c1_entry, [c1_row], 1)

    return paths


def count_paths() -> int:
    return len(generate_all_paths())


# ===================================================================
# CALIBRACION - Pulsa F2 sin salir del juego
# ===================================================================

import ctypes

def _wait_f2() -> tuple[int, int]:
    """Espera a que el usuario pulse F2 y devuelve la posicion del raton."""
    user32 = ctypes.windll.user32
    VK_F2 = 0x71

    # Esperar a que suelte F2 primero (por si la tenia pulsada)
    while user32.GetAsyncKeyState(VK_F2) & 0x8000:
        time.sleep(0.05)

    # Esperar a que pulse F2
    while not (user32.GetAsyncKeyState(VK_F2) & 0x8000):
        time.sleep(0.05)

    pos = pyautogui.position()

    # Esperar a que suelte
    while user32.GetAsyncKeyState(VK_F2) & 0x8000:
        time.sleep(0.05)

    return (pos.x, pos.y)


def _capture_f2(label: str) -> tuple[int, int]:
    """Muestra instruccion y espera F2 para capturar posicion."""
    click.echo(f"\n  >> {label}")
    click.echo(f"     Pon el raton encima y pulsa F2")
    pos = _wait_f2()
    click.echo(f"     OK: ({pos[0]}, {pos[1]})")
    return pos


@click.group()
def cli():
    """Albion Online Market Scanner."""
    pass


COL1_NAMES = [
    "Todo", "Armas", "Armadura Pecho", "Armadura Cabeza", "Armadura Pies",
    "Armas Secundarias", "Capas", "Bolsas", "Montura", "Consumible",
    "Equipo Recoleccion", "Fabricacion", "Artefacto", "Agricultura",
    "Mueble", "Cosmetica", "Otros",
]


@cli.command()
def calibrate():
    """Calibracion COMPLETA: F2 en cada categoria + subcategorias."""
    click.echo("=" * 60)
    click.echo("  CALIBRACION COMPLETA - Pulsa F2 en cada punto")
    click.echo("=" * 60)
    click.echo()
    click.echo("  Quedate en el juego, pon el raton y pulsa F2.")
    click.echo("  No cambies de ventana!")
    click.echo()
    click.echo("  PASOS:")
    click.echo("  1. Desplegable (1 punto)")
    click.echo("  2. Todas las categorias de col1 (17 puntos)")
    click.echo("  3. Col2: 2 filas para calcular altura")
    click.echo("  4. Col3: 2 filas para calcular altura")
    click.echo()
    click.echo("  Total: 22 pulsaciones de F2")
    click.echo()

    # === DESPLEGABLE ===
    dd = _capture_f2("DESPLEGABLE (la fila que abre el menu)")

    # === COL1: TODAS LAS CATEGORIAS ===
    click.echo("\n  --- COL1: Las 17 filas (de arriba a abajo) ---")
    click.echo("  Abre el desplegable y ve pulsando F2 en cada fila:\n")

    col1_positions = []
    for i, name in enumerate(COL1_NAMES):
        pos = _capture_f2(f"Col1 fila {i}: '{name}'")
        col1_positions.append(pos)

    # Calcular col1_h como promedio entre filas consecutivas
    col1_x = col1_positions[0][0]
    diffs = [col1_positions[i+1][1] - col1_positions[i][1] for i in range(len(col1_positions)-1)]
    col1_h = sum(diffs) / len(diffs) if diffs else 25

    click.echo(f"\n  Col1 capturada: {len(col1_positions)} posiciones, h promedio={col1_h:.1f}px")

    # === COL2: ALTURA + OFFSET ===
    click.echo("\n  --- COL2: Altura + offset ---")
    click.echo("  IMPORTANTE: Hover ARMAS (la categoria col1 fila 1)")
    click.echo("  para que aparezca col2. NO te muevas a otra cat.\n")

    c2_first = _capture_f2("Col2: primera fila ('Todo')")
    c2_second = _capture_f2("Col2: segunda fila (primer arma, ej: Arco)")

    c2_h = c2_second[1] - c2_first[1]
    if c2_h <= 0:
        click.echo("  ERROR: segunda fila debe estar DEBAJO.")
        return

    # Offset: diferencia Y entre col2 "Todo" y el padre hovereado (Armas = col1[1])
    armas_y = col1_positions[1][1]
    c2_offset_y = c2_first[1] - armas_y

    click.echo(f"  Col2: h={c2_h}px, offset_y={c2_offset_y}px (relativo a Armas)")

    # === COL3: ALTURA + OFFSET ===
    click.echo("\n  --- COL3: Altura + offset ---")
    click.echo("  IMPORTANTE: Hover ARMAS, luego hover el PRIMER ARMA")
    click.echo("  (col2 fila 1, ej: Arco) para que aparezca col3.\n")

    c3_first = _capture_f2("Col3: primera fila ('Todo')")
    c3_second = _capture_f2("Col3: segunda fila (primer item)")

    c3_h = c3_second[1] - c3_first[1]
    if c3_h <= 0:
        click.echo("  ERROR: segunda fila debe estar DEBAJO.")
        return

    # Parent col2 hovereado = col2 fila 1 = c2_first + col2_h
    c2_row1_y = c2_first[1] + c2_h
    c3_offset_y = c3_first[1] - c2_row1_y

    click.echo(f"  Col3: h={c3_h}px, offset_y={c3_offset_y}px (relativo a col2 fila 1)")

    # Col4 estimada
    col_spacing_x = c3_first[0] - c2_first[0]
    c4_x = c3_first[0] + col_spacing_x

    # === TIERS (desplegable) ===
    click.echo("\n  --- DESPLEGABLE DE TIERS ---")
    click.echo("  Carga cualquier item para que se vean los filtros.")
    click.echo("  Primero captura el BOTON del desplegable de tiers.\n")
    tier_dd = _capture_f2("Boton desplegable de TIERS (cerrado)")
    click.echo("\n  Ahora abre el desplegable manualmente (click) y pulsa F2")
    click.echo("  en cada tier de T1 a T8:\n")
    tier_positions = []
    for t in range(1, 9):
        pos = _capture_f2(f"Opcion tier T{t}")
        tier_positions.append(pos)

    # === ENCANTAMIENTOS (desplegable) ===
    click.echo("\n  --- DESPLEGABLE DE ENCANTAMIENTOS ---")
    click.echo("  Primero captura el BOTON del desplegable de encantamientos.\n")
    ench_dd = _capture_f2("Boton desplegable de ENCANTAMIENTOS (cerrado)")
    click.echo("\n  Abre el desplegable manualmente y pulsa F2 en cada opcion:\n")
    ench_positions = []
    for e in range(5):
        pos = _capture_f2(f"Opcion encantamiento .{e}")
        ench_positions.append(pos)

    # === CALIDADES (desplegable) ===
    click.echo("\n  --- DESPLEGABLE DE CALIDADES ---")
    click.echo("  Primero captura el BOTON del desplegable de calidades.\n")
    qual_dd = _capture_f2("Boton desplegable de CALIDADES (cerrado)")
    click.echo("\n  Abre el desplegable manualmente y pulsa F2 en cada opcion")
    click.echo("  (Normal, Buena, Excepcional, Excelente, Obra Maestra):\n")
    qual_positions = []
    qual_names = ["Normal", "Buena", "Excepcional", "Excelente", "Obra Maestra"]
    for q, name in enumerate(qual_names, start=1):
        pos = _capture_f2(f"Calidad {q}: '{name}'")
        qual_positions.append(pos)

    # === GUARDAR ===
    calibration = {
        "dropdown_x": dd[0], "dropdown_y": dd[1],
        "col1_x": col1_x,
        "col1_y0": col1_positions[0][1],
        "col1_h": round(col1_h, 1),
        "col1_positions": col1_positions,  # posicion exacta de cada categoria
        "col2_x": c2_first[0],
        "col2_h": c2_h,
        "col2_offset_y": c2_offset_y,
        "col3_x": c3_first[0],
        "col3_h": c3_h,
        "col3_offset_y": c3_offset_y,
        "col4_x": c4_x,
        "col4_h": c3_h,
        "col4_offset_y": c3_offset_y,
        "tier_dropdown": list(tier_dd),
        "tier_positions": tier_positions,
        "ench_dropdown": list(ench_dd),
        "ench_positions": ench_positions,
        "qual_dropdown": list(qual_dd),
        "qual_positions": qual_positions,
    }

    CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CALIBRATION_FILE, "w") as f:
        json.dump(calibration, f, indent=2)

    total = count_paths()
    click.echo()
    click.echo("=" * 60)
    click.echo("  CALIBRACION COMPLETA")
    click.echo("=" * 60)
    click.echo(f"  Desplegable:  ({dd[0]}, {dd[1]})")
    click.echo(f"  Col1: {len(col1_positions)} posiciones exactas, h={col1_h:.1f}px")
    click.echo(f"  Col2: x={c2_first[0]}, h={c2_h}, offset={c2_offset_y}")
    click.echo(f"  Col3: x={c3_first[0]}, h={c3_h}, offset={c3_offset_y}")
    click.echo(f"  Col4: x={c4_x} (est), h={c3_h}, offset={c3_offset_y}")
    click.echo(f"  Total items: {total} (~{total * 2 // 60} min)")
    click.echo()
    click.echo("  python scripts/market_scanner.py scan")


# ===================================================================
# ESCANEO
# ===================================================================

@cli.command()
@click.option("--delay", "-d", default=0.8, help="Seg espera tras clic en item (default: 0.8)")
@click.option("--hover-delay", default=0.25, help="Seg espera tras cada hover (default: 0.25)")
@click.option("--start-delay", default=5, help="Seg antes de empezar (default: 5)")
@click.option("--start-from", default=0, help="Saltar los primeros N items (para reanudar)")
@click.option("--tiers", default="4,5,6,7,8", help="Tiers a escanear separados por coma (1-8). Vacio = solo el tier por defecto.")
@click.option("--enchants", default="0,1,2,3,4", help="Encantamientos a escanear (0-4). Vacio = solo .0.")
@click.option("--qualities", default="1,2,3,4,5", help="Calidades a escanear (1-5). Vacio = solo la por defecto.")
@click.option("--variant-delay", default=0.4, help="Seg entre cada variante (default: 0.4)")
def scan(delay: float, hover_delay: float, start_delay: int, start_from: int,
         tiers: str, enchants: str, qualities: str, variant_delay: float):
    """Escanear TODO el mercado automaticamente."""

    if not CALIBRATION_FILE.exists():
        click.echo("ERROR: Ejecuta primero: python scripts/market_scanner.py calibrate")
        return

    with open(CALIBRATION_FILE) as f:
        cal = json.load(f)

    # Posiciones exactas de col1 (calibradas con F2)
    col1_positions = cal.get("col1_positions")  # [[x,y], [x,y], ...] para las 17 filas
    if not col1_positions or len(col1_positions) < 17:
        click.echo("ERROR: Calibracion incompleta. Recalibra con: python scripts/market_scanner.py calibrate")
        return

    # X de cada columna
    col_x = {
        1: cal["col1_x"],
        2: cal["col2_x"],
        3: cal["col3_x"],
        4: cal["col4_x"],
    }
    # Altura de fila en cada columna
    col_h = {
        1: cal["col1_h"],
        2: cal["col2_h"],
        3: cal["col3_h"],
        4: cal["col4_h"],
    }
    # Offsets Y: cuanto se desplaza la primera fila de colN respecto al parent
    # col2_offset_y = Y(col2_fila0) - Y(col1_parent_hoverado)
    # col3_offset_y = Y(col3_fila0) - Y(col2_parent_hoverado)
    col_offset_y = {
        2: cal.get("col2_offset_y", 0),
        3: cal.get("col3_offset_y", 0),
        4: cal.get("col4_offset_y", 0),
    }

    dd_x, dd_y = cal["dropdown_x"], cal["dropdown_y"]

    # Tiers, enchants y calidades a escanear
    tier_positions = cal.get("tier_positions") or []
    ench_positions = cal.get("ench_positions") or []
    qual_positions = cal.get("qual_positions") or []
    tier_dd = cal.get("tier_dropdown")
    ench_dd = cal.get("ench_dropdown")
    qual_dd = cal.get("qual_dropdown")

    tier_list = [int(t) for t in tiers.split(",") if t.strip()] if tiers else []
    ench_list = [int(e) for e in enchants.split(",") if e.strip()] if enchants else []
    qual_list = [int(q) for q in qualities.split(",") if q.strip()] if qualities else []
    tier_list = [t for t in tier_list if 1 <= t <= 8 and tier_positions and tier_dd]
    ench_list = [e for e in ench_list if 0 <= e <= 4 and ench_positions and ench_dd]
    qual_list = [q for q in qual_list if 1 <= q <= 5 and qual_positions and qual_dd]
    use_variants = bool(tier_list or ench_list or qual_list)
    if not tier_list:
        tier_list = [None]
    if not ench_list:
        ench_list = [None]
    if not qual_list:
        qual_list = [None]
    variants_per_item = len(tier_list) * len(ench_list) * len(qual_list)

    # Generar todas las rutas
    all_paths = generate_all_paths()
    total = len(all_paths)

    if start_from > 0:
        all_paths = all_paths[start_from:]
        click.echo(f"  Saltando primeros {start_from} items, quedan {len(all_paths)}")

    click.echo("=" * 60)
    click.echo("  MARKET SCANNER - ESCANEO COMPLETO")
    click.echo("=" * 60)
    click.echo()
    click.echo(f"  Items totales:       {total}")
    click.echo(f"  Items a escanear:    {len(all_paths)}")
    click.echo(f"  Variantes por item:  {variants_per_item} (tiers={tier_list} ench={ench_list} qual={qual_list})")
    click.echo(f"  Total clics:         {len(all_paths) * variants_per_item}")
    click.echo(f"  Delay por item:      {delay}s")
    click.echo(f"  Delay por hover:     {hover_delay}s")
    per_item = delay + hover_delay * 3 + 0.5 + (variants_per_item - 1) * (variant_delay + 0.1)
    click.echo(f"  Tiempo estimado:     ~{len(all_paths) * per_item / 60:.0f} min")
    click.echo()
    click.echo(f"  Col offsets Y: col2={col_offset_y[2]}, col3={col_offset_y[3]}, col4={col_offset_y[4]}")
    click.echo()
    click.echo("  Esquina SUPERIOR-IZQUIERDA = ABORTAR")
    click.echo()
    click.echo(f"  Cambia al juego! Empieza en {start_delay} seg...")

    for i in range(start_delay, 0, -1):
        click.echo(f"  {i}...")
        time.sleep(1)

    click.echo()
    click.echo("  >>> ESCANEANDO...")
    click.echo()

    scanned = 0
    last_cat = -1

    try:
        for path in all_paths:
            # Mostrar progreso cuando cambia la categoria
            cat_idx = path[0] - 1  # 0-based
            if cat_idx != last_cat:
                last_cat = cat_idx
                cat_name = CATEGORY_NAMES[cat_idx] if cat_idx < len(CATEGORY_NAMES) else f"Cat {cat_idx+1}"
                click.echo(f"  [{scanned + start_from}/{total}] --- {cat_name} ---")

            # 1. Clic en desplegable para abrir menu
            pyautogui.click(dd_x, dd_y)
            time.sleep(0.3)

            # 2. Navegar por cada nivel de la ruta
            # Posicionamiento:
            #   col1: posicion EXACTA desde col1_positions[row] (calibrada)
            #   col2: parent_y + offset_y + row * h  (parent_y = Y del item col1)
            #   col3: parent_y + offset_y + row * h  (parent_y = Y del item col2)
            #   col4: parent_y + offset_y + row * h  (parent_y = Y del item col3)
            parent_y = 0

            for level_idx, row in enumerate(path):
                col_num = level_idx + 1
                cx = col_x[col_num]
                ch = col_h[col_num]

                if col_num == 1:
                    # Col1: usar posicion EXACTA calibrada
                    # row es 1-based (saltamos "Todo" en indice 0)
                    # col1_positions tiene 17 entradas: [Todo, Armas, ..., Otros]
                    # row=1 -> indice 1 (Armas), etc.
                    if row < len(col1_positions):
                        target_x = col1_positions[row][0]
                        target_y = col1_positions[row][1]
                    else:
                        # Fallback calculado
                        target_x = cx
                        target_y = col1_positions[0][1] + row * ch
                    cx = target_x  # usar X exacta de la calibracion
                else:
                    # Col2/3/4: empieza en parent_y + offset, desplazada por row * h
                    # row es 1-based (saltamos "Todo")
                    # fila 0 = "Todo" (la saltamos)
                    # fila 1 = primera opcion real
                    offset = col_offset_y.get(col_num, 0)
                    target_y = parent_y + offset + row * ch

                is_last = (level_idx == len(path) - 1)

                if is_last:
                    # Ultimo nivel: CLIC (carga ordenes, cierra menu)
                    pyautogui.click(cx, target_y)
                else:
                    # Niveles intermedios: HOVER (abre siguiente columna)
                    pyautogui.moveTo(cx, target_y)
                    time.sleep(hover_delay)
                    # La siguiente columna se posiciona relativa a este Y
                    parent_y = target_y

            # Esperar a que el sniffer capture la primera variante
            time.sleep(delay)

            # Iterar variantes: tier x enchant x calidad
            # Cada valor requiere: abrir desplegable -> clic opcion -> esperar
            def _select(dd_pos, options, idx):
                """Abre el desplegable y clica la opcion idx (0-based)."""
                pyautogui.click(dd_pos[0], dd_pos[1])
                time.sleep(0.25)
                ox, oy = options[idx]
                pyautogui.click(ox, oy)
                time.sleep(variant_delay)

            if use_variants:
                for tier in tier_list:
                    if tier is not None:
                        _select(tier_dd, tier_positions, tier - 1)
                    for ench in ench_list:
                        if ench is not None:
                            _select(ench_dd, ench_positions, ench)
                        for qual in qual_list:
                            if qual is not None:
                                _select(qual_dd, qual_positions, qual - 1)

            scanned += 1

            # Log cada 25 items
            if scanned % 25 == 0:
                click.echo(f"  [{scanned + start_from}/{total}] escaneados...")

    except KeyboardInterrupt:
        click.echo(f"\n  Detenido (Ctrl+C) en item {scanned + start_from}")
        click.echo(f"  Para reanudar: python scripts/market_scanner.py scan --start-from {scanned + start_from}")
    except pyautogui.FailSafeException:
        click.echo(f"\n  ABORT en item {scanned + start_from}")
        click.echo(f"  Para reanudar: python scripts/market_scanner.py scan --start-from {scanned + start_from}")

    click.echo()
    click.echo("=" * 60)
    click.echo(f"  COMPLETADO: {scanned} items escaneados")
    click.echo("=" * 60)
    click.echo()
    click.echo("  python scripts/market_scanner.py prices")


@cli.command()
def info():
    """Ver cuantos items se van a escanear por categoria."""
    paths = generate_all_paths()
    total = len(paths)

    # Contar por categoria
    counts = {}
    for path in paths:
        cat_idx = path[0] - 1
        cat_name = CATEGORY_NAMES[cat_idx] if cat_idx < len(CATEGORY_NAMES) else f"Cat {cat_idx+1}"
        counts[cat_name] = counts.get(cat_name, 0) + 1

    click.echo()
    click.echo(f"  {'Categoria':<25} {'Items':>8}")
    click.echo(f"  {'-'*35}")
    for name, count in counts.items():
        click.echo(f"  {name:<25} {count:>8}")
    click.echo(f"  {'-'*35}")
    click.echo(f"  {'TOTAL':<25} {total:>8}")
    click.echo()
    click.echo(f"  Tiempo estimado (1.5s/item): ~{total * 1.5 / 60:.0f} minutos")


# ===================================================================
# CONSULTAS DE PRECIOS
# ===================================================================

@cli.command()
@click.option("--item", "-i", default=None, help="Filtrar por item (ej: T4_BAG, SWORD)")
@click.option("--min-amount", "-a", default=1, help="Cantidad minima (default: 1)")
@click.option("--tier", "-t", default=None, help="Filtrar por tier (ej: T4, T5)")
@click.option("--export-csv", "-e", default=None, type=click.Path(), help="Exportar a CSV")
def prices(item, min_amount, tier, export_csv):
    """Precios MAS BAJOS de venta por cada item."""
    from sqlalchemy import text
    from albion_capture.core.config import load_config
    from albion_capture.core.database import create_db_engine
    from albion_capture.photon.operations import CITY_NAMES

    engine = create_db_engine(load_config().database)

    conditions = ["auction_type = 'offer'", "amount >= :min_amount"]
    params: dict = {"min_amount": min_amount}
    if item:
        conditions.append("item_albion_id ILIKE :item_filter")
        params["item_filter"] = f"%{item}%"
    if tier:
        t = tier.upper()
        if not t.startswith("T"): t = f"T{t}"
        conditions.append("item_albion_id LIKE :tier_filter")
        params["tier_filter"] = f"{t}_%"

    query = text(f"""
        WITH ranked AS (
            SELECT item_albion_id, quality_level, enchantment_level,
                   unit_price_silver, amount, expires_at, captured_at, city_id,
                   ROW_NUMBER() OVER (PARTITION BY item_albion_id ORDER BY unit_price_silver ASC) as rn
            FROM market_orders WHERE {" AND ".join(conditions)}
        )
        SELECT item_albion_id, quality_level, enchantment_level,
               unit_price_silver, amount, expires_at, captured_at, city_id
        FROM ranked WHERE rn = 1 ORDER BY item_albion_id
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        click.echo("No se encontraron ordenes de venta.")
        return

    click.echo(f"\n{'='*120}")
    click.echo(f"  PRECIOS MAS BAJOS DE VENTA - {len(rows)} items")
    click.echo(f"{'='*120}\n")
    click.echo(f"{'Item':<40} {'Q':>2} {'E':>2} {'Precio (silver)':>16} {'Cant':>6} {'Ciudad':<15} {'Capturado':<20}")
    click.echo("-" * 120)

    for r in rows:
        city = CITY_NAMES.get(r[7], str(r[7]))
        price = f"{r[3] / SILVER_DIVISOR:,.2f}"
        cap = str(r[6])[:16] if r[6] else "N/A"
        click.echo(f"{r[0]:<40} {r[1]:>2} {r[2]:>2} {price:>16} {r[4]:>6} {city:<15} {cap:<20}")

    click.echo(f"\nTotal: {len(rows)} items")

    if export_csv:
        import csv
        with open(export_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["item", "quality", "enchant", "price_silver", "amount", "expires", "captured", "city"])
            for r in rows:
                w.writerow([r[0], r[1], r[2], r[3]/SILVER_DIVISOR, r[4], r[5], r[6], CITY_NAMES.get(r[7], r[7])])
        click.echo(f"Exportado: {export_csv}")
    engine.dispose()


@cli.command()
@click.option("--item", "-i", required=True, help="Item a buscar")
@click.option("--limit", "-n", default=30)
def search(item, limit):
    """Buscar ordenes de venta de un item."""
    from sqlalchemy import text
    from albion_capture.core.config import load_config
    from albion_capture.core.database import create_db_engine
    from albion_capture.photon.operations import CITY_NAMES

    engine = create_db_engine(load_config().database)
    query = text("""
        SELECT item_albion_id, quality_level, enchantment_level,
               unit_price_silver, amount, city_id, expires_at, captured_at
        FROM market_orders WHERE auction_type = 'offer' AND item_albion_id ILIKE :f
        ORDER BY unit_price_silver ASC LIMIT :l
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"f": f"%{item}%", "l": limit}).fetchall()

    if not rows:
        click.echo(f"No hay ordenes para '{item}'.")
        return

    click.echo(f"\n  Ordenes de venta: {item}\n")
    click.echo(f"{'Item':<40} {'Q':>2} {'E':>2} {'Precio':>16} {'Cant':>6} {'Ciudad':<15}")
    click.echo("-" * 100)
    for r in rows:
        city = CITY_NAMES.get(r[5], str(r[5]))
        price = f"{r[3] / SILVER_DIVISOR:,.2f}"
        click.echo(f"{r[0]:<40} {r[1]:>2} {r[2]:>2} {price:>16} {r[4]:>6} {city:<15}")
    click.echo(f"\nTotal: {len(rows)}")
    engine.dispose()


@cli.command()
def status():
    """Resumen de datos capturados."""
    from sqlalchemy import text
    from albion_capture.core.config import load_config
    from albion_capture.core.database import create_db_engine

    engine = create_db_engine(load_config().database)
    with engine.connect() as conn:
        sell = conn.execute(text("SELECT COUNT(*) FROM market_orders WHERE auction_type='offer'")).scalar() or 0
        buy = conn.execute(text("SELECT COUNT(*) FROM market_orders WHERE auction_type='request'")).scalar() or 0
        unique = conn.execute(text("SELECT COUNT(DISTINCT item_albion_id) FROM market_orders WHERE auction_type='offer'")).scalar() or 0
        latest = conn.execute(text("SELECT MAX(captured_at) FROM market_orders")).scalar()
        top = conn.execute(text("""
            SELECT item_albion_id, COUNT(*) c, MIN(unit_price_silver) mn, MAX(unit_price_silver) mx
            FROM market_orders WHERE auction_type='offer'
            GROUP BY item_albion_id ORDER BY c DESC LIMIT 10
        """)).fetchall()

    click.echo(f"\n{'='*60}")
    click.echo(f"  ESTADO DE CAPTURA")
    click.echo(f"{'='*60}")
    click.echo(f"  Ventas:      {sell:,}")
    click.echo(f"  Compras:     {buy:,}")
    click.echo(f"  Items unicos:{unique:,}")
    click.echo(f"  Ultima:      {str(latest)[:19] if latest else 'N/A'}")

    if top:
        click.echo(f"\n  {'Item':<35} {'Ord':>6} {'Min':>12} {'Max':>12}")
        click.echo(f"  {'-'*68}")
        for r in top:
            click.echo(f"  {r[0]:<35} {r[1]:>6} {r[2]/SILVER_DIVISOR:>12,.2f} {r[3]/SILVER_DIVISOR:>12,.2f}")
    click.echo()
    engine.dispose()


if __name__ == "__main__":
    cli()
