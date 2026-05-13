"""Descarga y extrae las recetas de crafteo de Albion desde ao-bin-dumps raw.

Genera: server/data/recipes.json

Estructura del output:
{
  "count": N,
  "recipes": {
     "T4_2H_AXE": {
        "materials": [{"id": "T4_METALBAR", "count": 8}, {"id": "T4_PLANKS", "count": 16}],
        "silver_fee": 192,         # fee base marcado por el juego (no siempre se aplica)
        "focus": 66,               # foco consumido si craftas con foco
        "item_value": 768,         # itemvalue del juego (para nutrition y tax)
        "tier": 4,
        "crafting_category": "axe"
     }, ...
  }
}

Fuente: https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/items.json (RAW, ~80-100MB)

Ejecutar: py scripts/fetch_recipes.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/items.json"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "server" / "data" / "recipes.json"


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _int(v, default=0) -> int:
    try: return int(v)
    except (TypeError, ValueError): return default


def extract(items_root: dict) -> dict:
    """items_root = contenido de root['items'] con nodos 'equipmentitem', 'weapon',
    'consumableitem', 'mount', 'farmableitem', etc."""
    recipes: dict[str, dict] = {}

    for _type, nodes in items_root.items():
        if not isinstance(nodes, (list, dict)):
            continue
        for it in (nodes if isinstance(nodes, list) else [nodes]):
            if not isinstance(it, dict):
                continue
            uid = it.get("@uniquename")
            if not uid or not isinstance(uid, str):
                continue
            # solo item base: descartamos variantes con @N (encantados) o _LEVEL
            if "@" in uid or "_LEVEL" in uid:
                continue

            cr = it.get("craftingrequirements")
            if not cr:
                continue

            # craftingrequirements puede ser dict o lista de dicts (variantes)
            # Tomamos la receta con mas materiales (suele ser la variante "estandar").
            best: dict | None = None
            for rec in _as_list(cr):
                if not isinstance(rec, dict):
                    continue
                res = _as_list(rec.get("craftresource"))
                mats = []
                for r in res:
                    if not isinstance(r, dict):
                        continue
                    mid = r.get("@uniquename")
                    c = _int(r.get("@count"))
                    if mid and c > 0:
                        mats.append({"id": mid, "count": c})
                if not mats:
                    continue
                cand = {
                    "materials": mats,
                    "silver_fee": _int(rec.get("@silver")),
                    "focus": _int(rec.get("@craftingfocus")),
                }
                if best is None or sum(m["count"] for m in mats) > sum(m["count"] for m in best["materials"]):
                    best = cand
            if not best:
                continue

            best["item_value"] = _int(it.get("@itemvalue"))
            best["tier"] = _int(it.get("@tier"))
            best["crafting_category"] = it.get("@craftingcategory") or it.get("@shopsubcategory")
            recipes[uid] = best

    return recipes


def main() -> int:
    print(f"[fetch] {URL}", flush=True)
    req = urllib.request.Request(URL, headers={"User-Agent": "albion-market-collector/1.0"})
    with urllib.request.urlopen(req, timeout=600) as r:
        raw = r.read()
    print(f"[fetch] {len(raw)/1e6:.1f} MB, parseando JSON (esto puede tardar ~10s)...", flush=True)
    data = json.loads(raw)
    items_root = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items_root, dict):
        print("[error] estructura inesperada en items.json", file=sys.stderr)
        return 2

    recipes = extract(items_root)
    print(f"[build] {len(recipes)} recetas extraidas", flush=True)

    # Estadisticas por categoria
    by_cat: dict[str, int] = {}
    for r in recipes.values():
        c = r.get("crafting_category") or "other"
        by_cat[c] = by_cat.get(c, 0) + 1
    print("[stats] top crafting_category:")
    for k, n in sorted(by_cat.items(), key=lambda x: -x[1])[:20]:
        print(f"   {k:24s} {n}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"count": len(recipes), "recipes": recipes}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"[save] {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
