"""Descarga y construye el catalogo de items de Albion Online.

Fuente: https://github.com/ao-data/ao-bin-dumps (formatted/items.json)

Genera:
    server/data/catalog.json

El catalogo contiene, por cada item base (sin encantamiento):
    id         UniqueName sin @enchant, e.g. "T4_2H_AXE"
    tier       int 1..8 (o 0 si no aplica)
    name_en    nombre ingles
    name_es    nombre espanol (fallback a name_en)
    category   grupo principal (weapon, armor, accessory, consumable, artifact, mount, furniture, resource, misc)
    subcategory  tipo dentro del grupo (sword, axe, head_cloth, cape, bag, potion, food, ...)
    slot       slot de equipo si aplica (mainhand, offhand, twohand, head, chest, shoes, cape, bag, mount, ...)
    enchantable  bool (si puede tener encantamiento)

Ejecutar con: py scripts/fetch_catalog.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

SRC_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.json"

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "server" / "data" / "catalog.json"


# ------------------------------------------------------------------
# Clasificador por regex sobre el UniqueName
# ------------------------------------------------------------------

WEAPON_TYPES: dict[str, list[str]] = {
    # nombre visible -> patrones
    "sword": ["SWORD", "CLAYMORE", "CARVING", "CLAWS", "GALATINE", "KINGMAKER"],
    "axe": ["AXE", "HALBERD", "GREATAXE", "BATTLEAXE", "REALMBREAKER", "CARRIONCALLER", "BEARPAWS"],
    "mace": ["MACE", "MORNINGSTAR", "HEAVYMACE", "CAMLANN", "OATHKEEPERS", "INCUBUS"],
    "hammer": ["HAMMER", "POLEHAMMER", "GROVEKEEPER", "FORGEHAMMER", "HAND_OF_JUSTICE", "TOMBHAMMER"],
    "dagger": ["DAGGER", "DAGGERPAIR", "CLAWS", "BLOODLETTER", "BRIDLED", "DEATHGIVERS", "BLACK_HANDS"],
    "bow": ["BOW", "LONGBOW", "WARBOW", "WAILING", "WHISPERING", "BADON"],
    "crossbow": ["CROSSBOW", "HEAVYCROSSBOW", "WEEPING", "BOLTCASTERS", "SIEGEBOW"],
    "spear": ["SPEAR", "PIKE", "GLAIVE", "HEROIC", "TRINITY", "DAYBREAKER"],
    "quarterstaff": ["QUARTERSTAFF", "IRON_CLAD", "IRONCLAD", "DOUBLE_BLADED", "BLACK_MONK", "STAFF_OF_BALANCE"],
    "fire_staff": ["FIRESTAFF", "GREATFIRESTAFF", "INFERNO", "WILDFIRE", "BRIMSTONE", "BLAZING"],
    "holy_staff": ["HOLYSTAFF", "GREATHOLY", "DIVINE", "LIFETOUCHSTAFF", "FALLEN", "REDEMPTION"],
    "arcane_staff": ["ARCANESTAFF", "GREATARCANE", "WITCHWORK", "ENIGMATIC", "MALEVOLENT", "OCCULT"],
    "frost_staff": ["FROSTSTAFF", "GREATFROST", "GLACIAL", "HOARFROST", "ICICLE", "PERMAFROST"],
    "nature_staff": ["NATURESTAFF", "GREATNATURE", "DRUIDIC", "WILDSTAFF", "FORESTHEART", "BLIGHT"],
    "curse_staff": ["CURSEDSTAFF", "GREATCURSED", "DEMONIC", "LOCUS", "SHADOWCALLER", "DAMNATION"],
    "shield": ["SHIELD", "CAITIFF", "SARCOPHAGUS", "FACEBREAKER"],
    "torch": ["TORCH"],
    "horn": ["HORN"],
    "book": ["BOOK"],
    "orb": ["ORB"],
    "totem": ["TOTEM"],
    "tome": ["TOME"],
}

TOOL_TYPES: dict[str, list[str]] = {
    "pickaxe": ["PICK", "PICKAXE"],
    "sickle": ["SICKLE"],
    "skinningknife": ["KNIFE"],
    "stonehammer": ["STONEHAMMER"],
    "woodaxe": ["WOODAXE"],
    "fishing_rod": ["FISHING"],
    "demolition_hammer": ["DEMOLITIONHAMMER"],
}

ACCESSORY_TYPES: dict[str, list[str]] = {
    "cape": ["CAPE", "CAPEITEM"],
    "bag": ["BAG"],
}

CONSUMABLE_TYPES: dict[str, list[str]] = {
    "potion": ["POTION"],
    "food": ["MEAL", "FISH_FRESHWATER", "FISH_SALTWATER", "OMELETTE", "PIE", "ROAST", "SALAD", "SANDWICH", "SOUP", "STEW"],
    "fish": ["FISH"],
    "gatherer_food": ["CHEESE", "BREAD"],
}

MOUNT_TYPES: dict[str, list[str]] = {
    "horse": ["HORSE"],
    "ox": ["OX"],
    "swiftclaw": ["SWIFTCLAW"],
    "direwolf": ["DIREWOLF"],
    "giantstag": ["GIANTSTAG", "STAG"],
    "mammoth": ["MAMMOTH"],
    "armored_horse": ["ARMOREDHORSE"],
    "battle_eagle": ["EAGLE"],
    "bear": ["BEAR"],
    "cougar": ["COUGAR"],
    "mount_other": ["MOUNT"],
}

RESOURCE_TYPES: dict[str, list[str]] = {
    "wood": ["WOOD", "PLANKS"],
    "ore": ["ORE", "METALBAR"],
    "hide": ["HIDE", "LEATHER"],
    "fiber": ["FIBER", "CLOTH"],
    "rock": ["ROCK", "STONEBLOCK"],
    "gem": ["RUNE", "SOUL", "RELIC"],
}

FURNITURE_HINT = ("UNIQUE_FURNITURE", "UNIQUE_TROPHY", "UNIQUE_BANNER", "UNIQUE_DECO",
                  "FURNITUREITEM", "FURNITURE_", "TROPHY_")

FARMING_HINT = ("FARM_", "SEED_", "CARROT_SEED", "BEAN_SEED", "WHEAT_SEED",
                "TURNIP_SEED", "CABBAGE_SEED", "POTATO_SEED", "CORN_SEED",
                "PUMPKIN_SEED", "AGARIC", "COMFREY", "BURDOCK", "TEASEL", "FOXGLOVE", "MULLEIN", "YARROW",
                "CALFBABY", "GOOSEBABY", "CHICKENBABY", "GOATBABY", "SHEEPBABY", "PIGBABY",
                "COW_", "GOOSE_", "CHICKEN_", "GOAT_", "SHEEP_", "PIG_")

JOURNAL_HINT = ("JOURNAL_",)
ARTIFACT_HINT = ("ARTEFACT", "ARTIFACT", "RUNE_T", "SOUL_T", "RELIC_T")
LABORER_HINT = ("LABORER", "LABORERITEM")


def _tier_from_id(uid: str) -> int:
    m = re.match(r"^T(\d)_", uid)
    return int(m.group(1)) if m else 0


def _strip_tier(uid: str) -> str:
    return re.sub(r"^T\d+_", "", uid)


def classify(uid: str) -> tuple[str, str, str | None]:
    """Devuelve (category, subcategory, slot)."""
    s = _strip_tier(uid)

    # --- furniture / decor ---
    if any(h in uid for h in FURNITURE_HINT):
        return "furniture", "furniture", None

    # --- farming / animals ---
    if any(h in uid for h in FARMING_HINT):
        if "SEED" in uid: return "farming", "seed", None
        if "BABY" in uid or "_EGG" in uid: return "farming", "animal_baby", None
        if uid.startswith("T1_FARM_") or uid.startswith("T2_FARM_") or "_HARVEST" in uid:
            return "farming", "crop", None
        return "farming", "farm", None

    # --- journals ---
    if any(h in uid for h in JOURNAL_HINT):
        return "journal", "journal", None

    # --- laborer items ---
    if any(h in uid for h in LABORER_HINT):
        return "laborer", "laborer", None

    # --- artifacts y runas sueltas (materiales de crafteo) ---
    if any(h in uid for h in ARTIFACT_HINT) and "MAIN_" not in uid and "2H_" not in uid and "OFF_" not in uid:
        return "artifact_material", "artifact", None

    # --- mount ---
    for name, pats in MOUNT_TYPES.items():
        if any(p in uid for p in pats):
            return "mount", name, "mount"

    # --- weapon ---
    m = re.match(r"^(2H|MAIN|OFF)_", s)
    if m:
        hand = {"2H": "twohand", "MAIN": "mainhand", "OFF": "offhand"}[m.group(1)]
        rest = s[len(m.group(1)) + 1:]
        for name, pats in WEAPON_TYPES.items():
            if any(p in rest for p in pats):
                return "weapon", name, hand
        return "weapon", "other", hand

    # --- tool ---
    for name, pats in TOOL_TYPES.items():
        if any(p in uid for p in pats):
            return "tool", name, "twohand"

    # --- armor (HEAD/ARMOR/SHOES) ---
    m = re.match(r"^(HEAD|ARMOR|SHOES)_(CLOTH|LEATHER|PLATE)", s)
    if m:
        slot = {"HEAD": "head", "ARMOR": "chest", "SHOES": "shoes"}[m.group(1)]
        mat = m.group(2).lower()
        return "armor", f"{mat}_{slot}", slot
    # armor con nombre unico: T4_HEAD_PLATE_SET1 vs artefactos HEAD_CLOTH_MORGANA
    m = re.match(r"^(HEAD|ARMOR|SHOES)_", s)
    if m:
        slot = {"HEAD": "head", "ARMOR": "chest", "SHOES": "shoes"}[m.group(1)]
        return "armor", "artifact_" + slot, slot

    # --- accessory ---
    for name, pats in ACCESSORY_TYPES.items():
        if any(s.startswith(p) or p == s for p in pats):
            return "accessory", name, name
    if s.startswith("CAPE"):
        return "accessory", "cape", "cape"
    if s.startswith("BAG"):
        return "accessory", "bag", "bag"

    # --- consumable ---
    for name, pats in CONSUMABLE_TYPES.items():
        if any(p in uid for p in pats):
            return "consumable", name, None

    # --- resources / materials ---
    for name, pats in RESOURCE_TYPES.items():
        if any(uid.endswith("_" + p) or f"_{p}_" in uid or uid.endswith(p) for p in pats):
            return "resource", name, None

    # --- tesoros, mapas, tomos, misc ---
    if "TREASURE" in uid or "MAP_" in uid or "TOME_" in uid:
        return "misc", "treasure", None
    if "TRASH" in uid or "VANITY" in uid or "SKIN_" in uid:
        return "misc", "vanity", None

    return "misc", "other", None


# ------------------------------------------------------------------
# Build
# ------------------------------------------------------------------

def build() -> dict:
    print(f"[fetch] Bajando {SRC_URL} ...", flush=True)
    req = urllib.request.Request(SRC_URL, headers={"User-Agent": "albion-market-collector/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8")
    items = json.loads(raw)
    print(f"[fetch] Recibidos {len(items)} items", flush=True)

    catalog: dict[str, dict] = {}
    for it in items:
        uid_raw = str(it.get("UniqueName") or "").strip()
        if not uid_raw:
            continue
        # Quitamos encantamientos: T4_2H_AXE@3 -> T4_2H_AXE
        uid = uid_raw.split("@", 1)[0]
        if uid in catalog:
            continue

        names = it.get("LocalizedNames") or {}
        name_en = names.get("EN-US") or uid
        name_es = names.get("ES-ES") or name_en
        cat, sub, slot = classify(uid)
        tier = _tier_from_id(uid)
        enchantable = bool(re.search(r"_(2H|MAIN|OFF|HEAD|ARMOR|SHOES|CAPE|BAG)(_|$)", uid))

        catalog[uid] = {
            "id": uid,
            "tier": tier,
            "name_en": name_en,
            "name_es": name_es,
            "category": cat,
            "subcategory": sub,
            "slot": slot,
            "enchantable": enchantable,
        }

    # Estadisticas por categoria
    by_cat: dict[str, int] = {}
    for v in catalog.values():
        by_cat[v["category"]] = by_cat.get(v["category"], 0) + 1
    print("[stats] items por categoria:")
    for k, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"   {k:20s} {n}")

    return {"version": 1, "count": len(catalog), "items": list(catalog.values())}


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[save] {OUT} ({OUT.stat().st_size/1024:.0f} KB, {data['count']} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
