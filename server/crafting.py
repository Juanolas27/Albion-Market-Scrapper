"""Carga de recetas + calculo de rentabilidad de crafteo por ciudad."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RECIPES_PATH = Path(__file__).parent / "data" / "recipes.json"

_CACHE: dict[str, Any] = {}


def _load() -> dict[str, Any]:
    if _CACHE:
        return _CACHE
    if not RECIPES_PATH.exists():
        _CACHE["recipes"] = {}
        return _CACHE
    data = json.loads(RECIPES_PATH.read_text(encoding="utf-8"))
    _CACHE["recipes"] = data.get("recipes") or {}
    return _CACHE


def get(item_id: str) -> dict | None:
    return _load()["recipes"].get(item_id)


def all_recipes() -> dict:
    return _load()["recipes"]


# ======================================================================
# Ciudades de bonus de crafteo y return rate
# ======================================================================

# Mapeo de crafting_category -> ciudad con bonus (return rate mas alto).
# Basado en los bonus actuales del juego.
BONUS_CITIES: dict[str, str] = {
    # Thetford: leather + cursed + frost
    "leather_helmet": "Thetford", "leather_armor": "Thetford", "leather_shoes": "Thetford",
    "cursedstaff": "Thetford", "froststaff": "Thetford",
    # Fort Sterling: plate + hammer + holy
    "plate_helmet": "Fort Sterling", "plate_armor": "Fort Sterling", "plate_shoes": "Fort Sterling",
    "hammer": "Fort Sterling", "holystaff": "Fort Sterling",
    # Lymhurst: cloth + sword + bow + arcane
    "cloth_helmet": "Lymhurst", "cloth_armor": "Lymhurst", "cloth_shoes": "Lymhurst",
    "sword": "Lymhurst", "arcanestaff": "Lymhurst", "bow": "Lymhurst",
    # Martlock: axe + quarterstaff + nature
    "axe": "Martlock", "quarterstaff": "Martlock", "naturestaff": "Martlock",
    # Bridgewatch: crossbow + dagger + fire
    "crossbow": "Bridgewatch", "dagger": "Bridgewatch", "firestaff": "Bridgewatch",
    # Spear -> Martlock tambien (actualizaciones de balance lo cambiaron)
    "spear": "Martlock",
    # Offhand varia, dejamos sin bonus por defecto
}

# Return rates aprox. (tax ya descontada -> lo que realmente recuperas de materiales).
# Valores redondeados para la estimacion de beneficio.
RETURN_RATE = {
    "no_focus_normal": 0.152,
    "no_focus_bonus": 0.248,
    "focus_normal": 0.435,
    "focus_bonus": 0.539,
}

# Fee del mercado al poner la orden de venta (setup + tax).
MARKET_FEE_NORMAL = 0.065   # 4% tax + 2.5% setup aprox
MARKET_FEE_BLACK = 0.03

# Estimacion de crafting fee:
#   nutrition = 5 * item_value  (por item crafteado)
#   fee_silver = nutrition * price_per_100_nutrition / 100
# Por defecto price_per_100_nutrition = 800 (ajustable por parametro).
DEFAULT_FEE_PER_100_NUTRITION = 800


def return_rate(city: str, crafting_category: str | None, use_focus: bool) -> float:
    is_bonus = bool(crafting_category) and BONUS_CITIES.get(crafting_category) == city
    if use_focus:
        return RETURN_RATE["focus_bonus" if is_bonus else "focus_normal"]
    return RETURN_RATE["no_focus_bonus" if is_bonus else "no_focus_normal"]


def is_bonus_city(city: str, crafting_category: str | None) -> bool:
    return bool(crafting_category) and BONUS_CITIES.get(crafting_category) == city


def crafting_fee(item_value: int, fee_per_100_nut: int = DEFAULT_FEE_PER_100_NUTRITION) -> float:
    """Fee estimada por UNIDAD crafteada."""
    nutrition = 5.0 * max(0, int(item_value or 0))
    return nutrition * fee_per_100_nut / 100.0


def market_fee_for(city: str) -> float:
    return MARKET_FEE_BLACK if city == "Black Market" else MARKET_FEE_NORMAL
