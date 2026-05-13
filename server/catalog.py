"""Carga y expone el catalogo de items (generado por scripts/fetch_catalog.py)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).parent / "data" / "catalog.json"

_CACHE: dict[str, Any] = {}


def _load() -> dict[str, Any]:
    if _CACHE:
        return _CACHE
    if not CATALOG_PATH.exists():
        _CACHE["items"] = []
        _CACHE["by_id"] = {}
        _CACHE["categories"] = []
        return _CACHE
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    items = data.get("items", [])
    _CACHE["items"] = items
    _CACHE["by_id"] = {it["id"]: it for it in items}

    # Estructura de categorias -> subcategorias con conteo
    cats: dict[str, dict[str, int]] = {}
    for it in items:
        c = it.get("category") or "misc"
        s = it.get("subcategory") or "other"
        cats.setdefault(c, {}).setdefault(s, 0)
        cats[c][s] += 1
    _CACHE["categories"] = [
        {
            "category": c,
            "count": sum(subs.values()),
            "subcategories": sorted(
                [{"id": sc, "count": n} for sc, n in subs.items()],
                key=lambda x: -x["count"],
            ),
        }
        for c, subs in sorted(cats.items(), key=lambda x: -sum(x[1].values()))
    ]
    return _CACHE


def all_items() -> list[dict]:
    return _load()["items"]


def by_id(item_id: str) -> dict | None:
    return _load()["by_id"].get(item_id)


def categories() -> list[dict]:
    return _load()["categories"]


def search(
    q: str = "",
    category: str = "",
    subcategory: str = "",
    tier: int | None = None,
    lang: str = "es",
    limit: int = 500,
) -> list[dict]:
    items = _load()["items"]
    q_low = q.strip().lower()
    name_key = "name_es" if lang == "es" else "name_en"
    out = []
    for it in items:
        if category and it.get("category") != category:
            continue
        if subcategory and it.get("subcategory") != subcategory:
            continue
        if tier is not None and tier > 0 and it.get("tier") != tier:
            continue
        if q_low:
            # match en nombre espanol, ingles o id
            if (q_low not in it.get("name_es", "").lower()
                    and q_low not in it.get("name_en", "").lower()
                    and q_low not in it["id"].lower()):
                continue
        out.append(it)
        if len(out) >= limit:
            break
    return out
