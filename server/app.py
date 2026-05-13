"""Albion Market central server.

Recibe ordenes/historial/gold de sniffers remotos via HTTP + API key por usuario.
Expone web viewer publico de consulta.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import and_, func, insert, or_, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .auth import (
    _load_user_or_401,
    generate_api_key,
    get_client_ip,
    hash_key,
    record_access,
    require_admin,
    require_any_auth,
    require_session,
    require_user,
)
from . import catalog as catalog_mod
from . import crafting as crafting_mod
from .db import Base, SessionLocal, engine, get_db, run_migrations
from .models import AccessLog, GoldPrice, MarketHistory, MarketOrder, User
from .schemas import (
    AdminCreateUserIn,
    AdminKeyOut,
    AdminRenameIn,
    GoldIn,
    HistoryIn,
    MeOut,
    OrderIn,
    StatsOut,
    UploadResponse,
    UserOut,
)


# ============================================================
# INIT
# ============================================================

Base.metadata.create_all(engine)
run_migrations()

app = FastAPI(
    title="Albion Market Collector",
    version="1.0.0",
    description="Servidor central de captura colaborativa de mercado de Albion Online.",
)


CITY_NAMES = {
    3000: "Thetford", 3002: "Fort Sterling", 3003: "Lymhurst",
    3004: "Martlock", 3005: "Bridgewatch", 3008: "Caerleon",
    3013: "Black Market", 4002: "Brecilien",
}

# Minimo de contribuciones diarias para ver los datos (admin exento)
DAILY_CONTRIB_THRESHOLD = 4000


def _utc_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _contributions_today(db: Session, user_id: int) -> int:
    day0 = _utc_day_start()
    orders = db.execute(
        select(func.count(MarketOrder.id)).where(
            MarketOrder.uploader_id == user_id,
            MarketOrder.captured_at >= day0,
        )
    ).scalar() or 0
    hist = db.execute(
        select(func.count(MarketHistory.id)).where(
            MarketHistory.uploader_id == user_id,
            MarketHistory.captured_at >= day0,
        )
    ).scalar() or 0
    return int(orders) + int(hist)


def require_viewer_gate(user: User = Depends(require_any_auth), db: Session = Depends(get_db)) -> User:
    """Admin pasa siempre. Otros necesitan >= DAILY_CONTRIB_THRESHOLD
    contribuciones de hoy (orders + history) para ver los datos."""
    if getattr(user, "is_admin", False):
        return user
    c = _contributions_today(db, user.id)
    if c < DAILY_CONTRIB_THRESHOLD:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "contribution_gate",
                "message": (
                    f"Necesitas al menos {DAILY_CONTRIB_THRESHOLD} contribuciones "
                    f"hoy para ver los datos. Llevas {c}."
                ),
                "contributions_today": c,
                "threshold": DAILY_CONTRIB_THRESHOLD,
            },
        )
    return user


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


# ============================================================
# INGESTA (requiere API key)
# ============================================================

MAX_BATCH = 1000


@app.post("/api/v1/orders", response_model=UploadResponse)
def upload_orders(
    orders: list[OrderIn],
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if len(orders) > MAX_BATCH:
        raise HTTPException(413, f"Batch too large (max {MAX_BATCH})")
    if not orders:
        return UploadResponse(received=0, inserted=0, updated=0)

    now = datetime.now(timezone.utc)
    rows = [{
        "order_id": o.order_id,
        "item_albion_id": o.item_albion_id,
        "city_id": o.city_id,
        "quality_level": o.quality_level,
        "enchantment_level": o.enchantment_level,
        "unit_price_silver": o.unit_price_silver,
        "amount": o.amount,
        "auction_type": o.auction_type,
        "tier": o.tier,
        "expires_at": o.expires_at,
        "captured_at": now,
        "updated_at": now,
        "uploader_id": user.id,
    } for o in orders]

    # Upsert sobre order_id. Contar insertados vs actualizados aproximado.
    existing_ids = {
        row[0] for row in db.execute(
            select(MarketOrder.order_id).where(
                MarketOrder.order_id.in_([o.order_id for o in orders])
            )
        )
    }

    stmt = sqlite_insert(MarketOrder).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["order_id"],
        set_={
            "unit_price_silver": stmt.excluded.unit_price_silver,
            "amount": stmt.excluded.amount,
            "updated_at": stmt.excluded.updated_at,
            "uploader_id": stmt.excluded.uploader_id,
        },
    )
    db.execute(stmt)

    inserted = len(rows) - len(existing_ids)
    updated = len(existing_ids)
    user.orders_uploaded += inserted
    db.commit()

    return UploadResponse(received=len(rows), inserted=inserted, updated=updated)


@app.post("/api/v1/history", response_model=UploadResponse)
def upload_history(
    entries: list[HistoryIn],
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if len(entries) > MAX_BATCH:
        raise HTTPException(413, f"Batch too large (max {MAX_BATCH})")
    if not entries:
        return UploadResponse(received=0, inserted=0, updated=0)

    now = datetime.now(timezone.utc)
    rows = [{
        "item_albion_id": h.item_albion_id,
        "city_id": h.city_id,
        "quality_level": h.quality_level,
        "timescale": h.timescale,
        "item_amount": h.item_amount,
        "silver_amount": h.silver_amount,
        "avg_price": h.avg_price,
        "timestamp": h.timestamp,
        "captured_at": now,
        "uploader_id": user.id,
    } for h in entries]

    stmt = sqlite_insert(MarketHistory).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["item_albion_id", "city_id", "quality_level", "timescale", "timestamp"]
    )
    result = db.execute(stmt)
    inserted = result.rowcount or 0

    user.history_uploaded += inserted
    db.commit()
    return UploadResponse(received=len(rows), inserted=inserted, updated=len(rows) - inserted)


@app.post("/api/v1/gold", response_model=UploadResponse)
def upload_gold(
    entries: list[GoldIn],
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not entries:
        return UploadResponse(received=0, inserted=0, updated=0)

    now = datetime.now(timezone.utc)
    rows = [{
        "price": g.price,
        "timestamp": g.timestamp,
        "captured_at": now,
        "uploader_id": user.id,
    } for g in entries]

    stmt = sqlite_insert(GoldPrice).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["timestamp"])
    result = db.execute(stmt)
    inserted = result.rowcount or 0
    db.commit()
    return UploadResponse(received=len(rows), inserted=inserted, updated=len(rows) - inserted)


# ============================================================
# CONSULTA PUBLICA
# ============================================================

@app.get("/api/v1/cities")
def cities(_: User = Depends(require_any_auth), db: Session = Depends(get_db)):
    ids = [r[0] for r in db.execute(select(MarketOrder.city_id).distinct().order_by(MarketOrder.city_id))]
    return [CITY_NAMES.get(i, str(i)) for i in ids]


@app.get("/api/v1/stats", response_model=StatsOut)
def stats(_: User = Depends(require_any_auth), db: Session = Depends(get_db)):
    total_orders = db.execute(select(func.count(MarketOrder.id))).scalar() or 0
    total_history = db.execute(select(func.count(MarketHistory.id))).scalar() or 0
    total_users = db.execute(select(func.count(User.id)).where(User.disabled == False)).scalar() or 0

    per_city = dict(
        db.execute(
            select(MarketOrder.city_id, func.count(MarketOrder.id)).group_by(MarketOrder.city_id)
        ).all()
    )

    top = db.execute(
        select(User.name, User.orders_uploaded, User.history_uploaded)
        .order_by(User.orders_uploaded.desc())
        .limit(10)
    ).all()
    top_list = [{"name": n, "orders": o, "history": h} for (n, o, h) in top]

    return StatsOut(
        total_orders=total_orders,
        total_history=total_history,
        total_users=total_users,
        cities=per_city,
        top_contributors=top_list,
    )


@app.get("/api/v1/items")
def items(
    item: str = "",
    tier: str = "",
    city: str = "",
    type: str = Query("", pattern="^(offer|request|)$"),
    mode: str = Query("lowest", pattern="^(lowest|all)$"),
    limit: int = Query(5000, ge=1, le=20000),
    _: User = Depends(require_viewer_gate),
    db: Session = Depends(get_db),
):
    where = []
    params: dict = {}

    if type:
        where.append("auction_type = :atype")
        params["atype"] = type
    if item:
        where.append("item_albion_id LIKE :item")
        params["item"] = f"%{item}%"
    if tier:
        where.append("item_albion_id LIKE :tier")
        params["tier"] = f"{tier}_%"
    if city:
        cid = next((k for k, v in CITY_NAMES.items() if v == city), None)
        if cid is not None:
            where.append("city_id = :cid")
            params["cid"] = cid

    wh = " AND ".join(where) if where else "1=1"

    if mode == "lowest":
        direction = "DESC" if type == "request" else "ASC"
        query = f"""
            WITH ranked AS (
                SELECT o.item_albion_id, o.quality_level, o.enchantment_level,
                       o.unit_price_silver, o.amount, o.city_id, o.captured_at,
                       u.name AS uploader,
                       ROW_NUMBER() OVER (
                           PARTITION BY o.item_albion_id, o.quality_level, o.enchantment_level, o.city_id, o.auction_type
                           ORDER BY o.unit_price_silver {direction}
                       ) AS rn
                FROM market_orders o
                LEFT JOIN users u ON u.id = o.uploader_id
                WHERE {wh.replace("auction_type", "o.auction_type").replace("item_albion_id", "o.item_albion_id").replace("city_id = :cid", "o.city_id = :cid")}
            )
            SELECT item_albion_id, quality_level, enchantment_level,
                   unit_price_silver, amount, city_id, captured_at, uploader
            FROM ranked WHERE rn = 1
            ORDER BY item_albion_id
            LIMIT :lim
        """
    else:
        query = f"""
            SELECT o.item_albion_id, o.quality_level, o.enchantment_level,
                   o.unit_price_silver, o.amount, o.city_id, o.captured_at,
                   u.name AS uploader
            FROM market_orders o
            LEFT JOIN users u ON u.id = o.uploader_id
            WHERE {wh.replace("auction_type", "o.auction_type").replace("item_albion_id", "o.item_albion_id").replace("city_id = :cid", "o.city_id = :cid")}
            ORDER BY o.captured_at DESC
            LIMIT :lim
        """
    params["lim"] = limit

    rows = db.execute(text(query), params).fetchall()
    unique = db.execute(text("SELECT COUNT(DISTINCT item_albion_id) FROM market_orders")).scalar() or 0
    total = db.execute(text("SELECT COUNT(*) FROM market_orders")).scalar() or 0
    latest = db.execute(text("SELECT MAX(captured_at) FROM market_orders")).scalar()

    result = [{
        "item_albion_id": r[0],
        "quality_level": r[1],
        "enchantment_level": r[2],
        "unit_price_silver": r[3],
        "amount": r[4],
        "city": CITY_NAMES.get(r[5], str(r[5])),
        "captured_at": r[6].isoformat() if hasattr(r[6], "isoformat") else r[6],
        "uploader": r[7] if len(r) > 7 else None,
    } for r in rows]

    return {
        "rows": result,
        "stats": {
            "unique": unique,
            "total": total,
            "latest": (latest.isoformat() if hasattr(latest, "isoformat") else str(latest))[:19].replace("T", " ") if latest else None,
        },
    }


# ============================================================
# CATALOGO DE ITEMS (fase 1)
# ============================================================

def _parse_id_ench(item_id: str) -> tuple[str, int]:
    """Divide 'T4_2H_AXE@3' -> ('T4_2H_AXE', 3). Si no hay @, ench=0."""
    if "@" in item_id:
        base, _, e = item_id.partition("@")
        try: return base, max(0, min(4, int(e)))
        except ValueError: return base, 0
    return item_id, 0


@app.get("/api/v1/catalog")
def catalog_list(
    q: str = Query("", max_length=80),
    category: str = "",
    subcategory: str = "",
    tier: int = Query(0, ge=0, le=8),
    lang: str = Query("es", pattern="^(es|en)$"),
    limit: int = Query(500, ge=1, le=3000),
    _: User = Depends(require_viewer_gate),
):
    rows = catalog_mod.search(
        q=q, category=category, subcategory=subcategory,
        tier=tier if tier else None, lang=lang, limit=limit,
    )
    return {"count": len(rows), "items": rows}


@app.get("/api/v1/catalog/categories")
def catalog_categories(_: User = Depends(require_viewer_gate)):
    return {"categories": catalog_mod.categories()}


@app.get("/api/v1/item/{item_id}")
def item_detail(
    item_id: str,
    quality: int = Query(0, ge=0, le=5),
    enchant: int = Query(-1, ge=-1, le=4),
    _: User = Depends(require_viewer_gate),
    db: Session = Depends(get_db),
):
    """Precios por ciudad para un item base.

    - item_id: UniqueName sin encantamiento (ej. 'T4_2H_AXE')
    - quality: 0 = cualquiera, 1-5 = filtro exacto
    - enchant: -1 = cualquiera, 0-4 = filtro exacto
    Devuelve, para cada ciudad, mejor oferta (venta mas barata) y mejor
    request (compra mas cara), con cantidad disponible, antiguedad y uploader.
    """
    base, _e = _parse_id_ench(item_id)
    meta = catalog_mod.by_id(base)

    where = ["item_albion_id LIKE :id_like"]
    params: dict = {"id_like": f"{base}%"}  # incluye encantamientos
    if quality > 0:
        where.append("quality_level = :q")
        params["q"] = quality
    if enchant >= 0:
        where.append("enchantment_level = :e")
        params["e"] = enchant
    wh = " AND ".join(where)

    # Para cada ciudad cogemos la mejor oferta y mejor request por city_id
    sql_offer = f"""
        WITH best AS (
            SELECT o.city_id, o.unit_price_silver, o.amount,
                   o.captured_at, o.quality_level, o.enchantment_level,
                   u.name AS uploader,
                   ROW_NUMBER() OVER (
                       PARTITION BY o.city_id
                       ORDER BY o.unit_price_silver ASC
                   ) AS rn
            FROM market_orders o
            LEFT JOIN users u ON u.id = o.uploader_id
            WHERE o.auction_type = 'offer' AND {wh}
        )
        SELECT city_id, unit_price_silver, amount, captured_at, quality_level, enchantment_level, uploader
        FROM best WHERE rn = 1
    """
    sql_request = f"""
        WITH best AS (
            SELECT o.city_id, o.unit_price_silver, o.amount,
                   o.captured_at, o.quality_level, o.enchantment_level,
                   u.name AS uploader,
                   ROW_NUMBER() OVER (
                       PARTITION BY o.city_id
                       ORDER BY o.unit_price_silver DESC
                   ) AS rn
            FROM market_orders o
            LEFT JOIN users u ON u.id = o.uploader_id
            WHERE o.auction_type = 'request' AND {wh}
        )
        SELECT city_id, unit_price_silver, amount, captured_at, quality_level, enchantment_level, uploader
        FROM best WHERE rn = 1
    """

    offers = {r[0]: r for r in db.execute(text(sql_offer), params).fetchall()}
    requests = {r[0]: r for r in db.execute(text(sql_request), params).fetchall()}

    cities_out = []
    for cid, cname in CITY_NAMES.items():
        o = offers.get(cid)
        r = requests.get(cid)
        cities_out.append({
            "city_id": cid,
            "city": cname,
            "offer": None if not o else {
                "price": o[1], "amount": o[2],
                "captured_at": o[3].isoformat() if hasattr(o[3], "isoformat") else str(o[3]) if o[3] else None,
                "quality": o[4], "enchant": o[5], "uploader": o[6],
            },
            "request": None if not r else {
                "price": r[1], "amount": r[2],
                "captured_at": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]) if r[3] else None,
                "quality": r[4], "enchant": r[5], "uploader": r[6],
            },
        })

    return {"item": meta, "base_id": base, "filters": {"quality": quality, "enchant": enchant}, "cities": cities_out}


# ============================================================
# FLIPS / VENTA RAPIDA (fase 3)
# ============================================================

MARKET_FEE_NORMAL = 0.045   # 4.5% setup + taxes aprox
MARKET_FEE_BLACK = 0.03     # 3% en black market


@app.get("/api/v1/flips")
def flips(
    max_age_min: int = Query(60, ge=1, le=1440),
    min_margin: int = Query(1000, ge=0),
    min_margin_pct: float = Query(0.0, ge=0.0, le=100.0),
    buy_city: str = "",
    sell_city: str = "",
    category: str = "",
    tier: int = Query(0, ge=0, le=8),
    limit: int = Query(300, ge=1, le=2000),
    _: User = Depends(require_viewer_gate),
    db: Session = Depends(get_db),
):
    """Oportunidades de arbitraje: comprar barato en una ciudad y vender
    caro en otra.

    - buy_city: filtra donde comprar (vacio = todas)
    - sell_city: filtra donde vender (vacio = todas)
    - El margen se calcula tras descontar la fee de la ciudad de venta
      (Black Market 3%, resto 4.5%).
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_min)

    buy_cid = next((k for k, v in CITY_NAMES.items() if v == buy_city), None)
    sell_cid = next((k for k, v in CITY_NAMES.items() if v == sell_city), None)

    # Construimos min oferta y max request por (item, q, e, city) dentro de la ventana
    offer_rows = db.execute(text("""
        SELECT item_albion_id, quality_level, enchantment_level, city_id,
               MIN(unit_price_silver) AS price, SUM(amount) AS total_amount,
               MAX(captured_at) AS last_capture
        FROM market_orders
        WHERE auction_type = 'offer' AND captured_at >= :cut
        GROUP BY item_albion_id, quality_level, enchantment_level, city_id
    """), {"cut": cutoff}).fetchall()

    request_rows = db.execute(text("""
        SELECT item_albion_id, quality_level, enchantment_level, city_id,
               MAX(unit_price_silver) AS price, SUM(amount) AS total_amount,
               MAX(captured_at) AS last_capture
        FROM market_orders
        WHERE auction_type = 'request' AND captured_at >= :cut
        GROUP BY item_albion_id, quality_level, enchantment_level, city_id
    """), {"cut": cutoff}).fetchall()

    # Indexar por (item, q, e)
    offers_by_key: dict[tuple[str, int, int], list] = {}
    for r in offer_rows:
        offers_by_key.setdefault((r[0], r[1], r[2]), []).append(r)
    requests_by_key: dict[tuple[str, int, int], list] = {}
    for r in request_rows:
        requests_by_key.setdefault((r[0], r[1], r[2]), []).append(r)

    out = []
    for key, offs in offers_by_key.items():
        reqs = requests_by_key.get(key)
        if not reqs:
            continue
        item_id, q, e = key
        meta = catalog_mod.by_id(item_id.split("@", 1)[0])
        if category and (not meta or meta.get("category") != category):
            continue
        if tier and (not meta or meta.get("tier") != tier):
            continue
        for o in offs:
            if buy_cid is not None and o[3] != buy_cid:
                continue
            for r in reqs:
                if sell_cid is not None and r[3] != sell_cid:
                    continue
                if o[3] == r[3]:
                    continue  # misma ciudad no es flip
                buy_price = int(o[4])
                sell_price = int(r[4])
                sell_city_name = CITY_NAMES.get(r[3], str(r[3]))
                fee = MARKET_FEE_BLACK if sell_city_name == "Black Market" else MARKET_FEE_NORMAL
                net_sell = sell_price * (1 - fee)
                margin = net_sell - buy_price
                if margin < min_margin:
                    continue
                margin_pct = (margin / buy_price * 100.0) if buy_price > 0 else 0.0
                if margin_pct < min_margin_pct:
                    continue
                out.append({
                    "item_id": item_id,
                    "name_es": (meta or {}).get("name_es") or item_id,
                    "name_en": (meta or {}).get("name_en") or item_id,
                    "category": (meta or {}).get("category"),
                    "tier": (meta or {}).get("tier"),
                    "quality": q,
                    "enchant": e,
                    "buy_city": CITY_NAMES.get(o[3], str(o[3])),
                    "buy_price": buy_price,
                    "buy_amount": int(o[5] or 0),
                    "buy_captured_at": o[6].isoformat() if hasattr(o[6], "isoformat") else str(o[6]) if o[6] else None,
                    "sell_city": sell_city_name,
                    "sell_price": sell_price,
                    "sell_amount": int(r[5] or 0),
                    "sell_captured_at": r[6].isoformat() if hasattr(r[6], "isoformat") else str(r[6]) if r[6] else None,
                    "fee_pct": round(fee * 100, 2),
                    "margin": int(round(margin)),
                    "margin_pct": round(margin_pct, 2),
                })

    out.sort(key=lambda x: x["margin"], reverse=True)
    return {
        "count": len(out),
        "rows": out[:limit],
        "filters": {
            "max_age_min": max_age_min, "min_margin": min_margin, "min_margin_pct": min_margin_pct,
            "buy_city": buy_city or None, "sell_city": sell_city or None,
            "category": category or None, "tier": tier or None,
        },
    }


# ============================================================
# CRAFTEOS (fase 4)
# ============================================================

@app.get("/api/v1/crafting")
def crafting(
    max_age_min: int = Query(120, ge=1, le=1440),
    use_focus: bool = Query(False),
    fee_per_100_nut: int = Query(800, ge=0, le=5000),
    min_profit: int = Query(0, ge=-10_000_000),
    category: str = "",
    tier: int = Query(0, ge=0, le=8),
    sell_to: str = Query("offer_undercut", pattern="^(offer_undercut|instant)$"),
    limit: int = Query(200, ge=1, le=2000),
    _: User = Depends(require_viewer_gate),
    db: Session = Depends(get_db),
):
    """Top crafteos rentables, por defecto ordenados por beneficio neto.

    Para cada receta, prueba todas las combinaciones (ciudad_origen_materiales,
    ciudad_destino_crafteo) y devuelve la mejor.

    - sell_to:
        * 'offer_undercut': asume que vendes en el mercado al precio de la
          oferta mas barata (venta pasiva). Ingreso = min_offer en ciudad destino.
        * 'instant': vendes a la orden de compra mas alta (venta instantanea).
          Ingreso = max_request en ciudad destino.
    - use_focus: aplica return rate con foco.
    - fee_per_100_nut: crafting fee por cada 100 nutrition (ajustable).
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_min)

    # 1) Precios de materiales: min(offer) por (item_id, quality=1, enchant=0, city)
    mat_rows = db.execute(text("""
        SELECT item_albion_id, city_id, MIN(unit_price_silver) AS price
        FROM market_orders
        WHERE auction_type = 'offer' AND quality_level = 1 AND enchantment_level = 0
          AND captured_at >= :cut
        GROUP BY item_albion_id, city_id
    """), {"cut": cutoff}).fetchall()
    # mat_price[(item_id, city_id)] = price
    mat_price: dict[tuple[str, int], int] = {(r[0], r[1]): int(r[2]) for r in mat_rows}

    # 2) Precios de venta del item crafteado en cada ciudad (quality=1, enchant=0)
    if sell_to == "offer_undercut":
        sell_rows = db.execute(text("""
            SELECT item_albion_id, city_id, MIN(unit_price_silver) AS price
            FROM market_orders
            WHERE auction_type = 'offer' AND quality_level = 1 AND enchantment_level = 0
              AND captured_at >= :cut
            GROUP BY item_albion_id, city_id
        """), {"cut": cutoff}).fetchall()
    else:  # instant
        sell_rows = db.execute(text("""
            SELECT item_albion_id, city_id, MAX(unit_price_silver) AS price
            FROM market_orders
            WHERE auction_type = 'request' AND quality_level = 1 AND enchantment_level = 0
              AND captured_at >= :cut
            GROUP BY item_albion_id, city_id
        """), {"cut": cutoff}).fetchall()
    sell_price: dict[tuple[str, int], int] = {(r[0], r[1]): int(r[2]) for r in sell_rows}

    # Solo ciudades con mercado normal para crafteo (excluimos Black Market como dest
    # de crafteo porque no hay estacion alli, pero permitimos vender alli).
    CRAFT_CITIES = {
        3000: "Thetford", 3002: "Fort Sterling", 3003: "Lymhurst",
        3004: "Martlock", 3005: "Bridgewatch", 3008: "Caerleon",
        4002: "Brecilien",
    }
    SELL_CITIES = dict(CITY_NAMES)  # incluye Black Market

    recipes = crafting_mod.all_recipes()

    results = []
    for item_id, rec in recipes.items():
        meta = catalog_mod.by_id(item_id)
        if not meta:
            continue
        if category and meta.get("category") != category:
            continue
        if tier and meta.get("tier") != tier:
            continue

        mats = rec.get("materials") or []
        if not mats:
            continue
        item_value = int(rec.get("item_value") or 0)
        craft_cat = rec.get("crafting_category")

        fee = crafting_mod.crafting_fee(item_value, fee_per_100_nut)

        best = None
        # Iteramos ciudad donde compras materiales
        for buy_cid, buy_cname in CRAFT_CITIES.items():
            # Coste total de materiales comprados en buy_cname
            total_cost = 0
            missing = False
            for m in mats:
                p = mat_price.get((m["id"], buy_cid))
                if p is None or p <= 0:
                    missing = True
                    break
                total_cost += p * int(m["count"])
            if missing:
                continue

            # Iteramos ciudad donde crafteas (usa return rate bonus si aplica)
            for craft_cid, craft_cname in CRAFT_CITIES.items():
                rr = crafting_mod.return_rate(craft_cname, craft_cat, use_focus)
                effective_mat_cost = total_cost * (1.0 - rr)
                is_bonus = crafting_mod.is_bonus_city(craft_cname, craft_cat)

                # Iteramos ciudad donde vendes
                for sell_cid, sell_cname in SELL_CITIES.items():
                    sp = sell_price.get((item_id, sell_cid))
                    if not sp:
                        continue
                    m_fee = crafting_mod.market_fee_for(sell_cname)
                    revenue = sp * (1.0 - m_fee)
                    profit = revenue - effective_mat_cost - fee

                    if best is None or profit > best["profit"]:
                        best = {
                            "item_id": item_id,
                            "name_es": meta.get("name_es") or item_id,
                            "name_en": meta.get("name_en") or item_id,
                            "tier": meta.get("tier"),
                            "category": meta.get("category"),
                            "crafting_category": craft_cat,
                            "buy_mats_city": buy_cname,
                            "craft_city": craft_cname,
                            "sell_city": sell_cname,
                            "bonus_city": is_bonus,
                            "return_rate": round(rr * 100, 1),
                            "use_focus": use_focus,
                            "focus_cost": int(rec.get("focus") or 0),
                            "materials_cost": int(round(total_cost)),
                            "effective_mat_cost": int(round(effective_mat_cost)),
                            "crafting_fee": int(round(fee)),
                            "sell_price": sp,
                            "market_fee_pct": round(m_fee * 100, 2),
                            "revenue_net": int(round(revenue)),
                            "profit": int(round(profit)),
                            "profit_pct": round((profit / max(effective_mat_cost + fee, 1)) * 100, 2),
                            "materials": mats,
                        }
        if best is None or best["profit"] < min_profit:
            continue
        results.append(best)

    results.sort(key=lambda x: x["profit"], reverse=True)
    return {
        "count": len(results),
        "rows": results[:limit],
        "filters": {
            "max_age_min": max_age_min, "use_focus": use_focus,
            "fee_per_100_nut": fee_per_100_nut, "min_profit": min_profit,
            "category": category or None, "tier": tier or None, "sell_to": sell_to,
        },
    }


# ============================================================
# WEB VIEWER
# ============================================================

WEB_HTML_PATH = Path(__file__).parent / "static" / "index.html"
ADMIN_HTML_PATH = Path(__file__).parent / "static" / "admin.html"
LOGIN_HTML_PATH = Path(__file__).parent / "static" / "login.html"

SESSION_COOKIE = "alb_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 dias


def _has_valid_session(request: Request, db: Session) -> bool:
    key = request.cookies.get(SESSION_COOKIE)
    if not key:
        return False
    try:
        _load_user_or_401(db, key)
        return True
    except HTTPException:
        return False


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    if not _has_valid_session(request, db):
        return RedirectResponse(url="/login", status_code=302)
    if WEB_HTML_PATH.exists():
        return HTMLResponse(WEB_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Albion Market Server</h1><p>Web viewer not deployed yet.</p>")


@app.get("/login", response_class=HTMLResponse)
def login_page():
    if LOGIN_HTML_PATH.exists():
        return HTMLResponse(LOGIN_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Login</h1><p>login.html not deployed.</p>")


@app.post("/api/v1/session")
def create_session(
    request: Request,
    response: Response,
    body: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Valida la API key y deja una cookie de sesion para el viewer web."""
    key = (body.get("api_key") or "").strip()
    if not key:
        raise HTTPException(400, "api_key requerido")
    user = _load_user_or_401(db, key)
    # registra acceso (y pinea device si es primera vez)
    record_access(db, user, request)
    user.last_seen_at = datetime.now(timezone.utc)
    db.commit()

    # cookie HttpOnly, Secure si servimos por HTTPS (Cloudflare siempre HTTPS).
    is_https = request.url.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https"
    response.set_cookie(
        key=SESSION_COOKIE,
        value=key,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=is_https,
        samesite="lax",
        path="/",
    )
    return {"ok": True, "name": user.name, "is_admin": bool(user.is_admin)}


@app.post("/api/v1/session/logout")
def destroy_session(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    if ADMIN_HTML_PATH.exists():
        return HTMLResponse(ADMIN_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Admin</h1><p>admin.html not deployed.</p>")


# ============================================================
# AUTH: info del usuario logueado
# ============================================================

@app.get("/api/v1/me", response_model=MeOut)
def me(user: User = Depends(require_any_auth), db: Session = Depends(get_db)):
    c = _contributions_today(db, user.id)
    allowed = bool(user.is_admin) or c >= DAILY_CONTRIB_THRESHOLD
    return MeOut(
        id=user.id, name=user.name, is_admin=bool(user.is_admin),
        contributions_today=c, threshold=DAILY_CONTRIB_THRESHOLD, allowed=allowed,
    )


@app.get("/api/v1/contributions")
def contributions(user: User = Depends(require_any_auth), db: Session = Depends(get_db)):
    """Ranking de contribuciones diarias por usuario. Cualquier usuario
    autenticado puede verlo (aunque este bloqueado por la puerta)."""
    day0 = _utc_day_start()
    orders_today = dict(db.execute(text("""
        SELECT uploader_id, COUNT(*) FROM market_orders
        WHERE uploader_id IS NOT NULL AND captured_at >= :d
        GROUP BY uploader_id
    """), {"d": day0}).fetchall())
    hist_today = dict(db.execute(text("""
        SELECT uploader_id, COUNT(*) FROM market_history
        WHERE uploader_id IS NOT NULL AND captured_at >= :d
        GROUP BY uploader_id
    """), {"d": day0}).fetchall())

    users = db.query(User).order_by(User.id).all()
    rows = []
    for u in users:
        ot = int(orders_today.get(u.id, 0))
        ht = int(hist_today.get(u.id, 0))
        today = ot + ht
        rows.append({
            "user_id": u.id,
            "name": u.name,
            "is_admin": bool(u.is_admin),
            "disabled": bool(u.disabled),
            "orders_today": ot,
            "history_today": ht,
            "contributions_today": today,
            "orders_total": int(u.orders_uploaded or 0),
            "history_total": int(u.history_uploaded or 0),
            "meets_threshold": bool(u.is_admin) or today >= DAILY_CONTRIB_THRESHOLD,
        })
    rows.sort(key=lambda x: x["contributions_today"], reverse=True)
    return {
        "threshold": DAILY_CONTRIB_THRESHOLD,
        "me": {
            "user_id": user.id,
            "name": user.name,
            "is_admin": bool(user.is_admin),
            "contributions_today": _contributions_today(db, user.id),
        },
        "rows": rows,
    }


# ============================================================
# ADMIN API (requiere user.is_admin = True)
# ============================================================

@app.get("/api/v1/admin/users", response_model=list[UserOut])
def admin_list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(User).order_by(User.id).all()


@app.post("/api/v1/admin/users", response_model=AdminKeyOut)
def admin_create_user(
    body: AdminCreateUserIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.name == body.name).first():
        raise HTTPException(409, f"Ya existe usuario '{body.name}'")
    key = generate_api_key()
    u = User(name=body.name, api_key_hash=hash_key(key))
    db.add(u)
    db.commit()
    db.refresh(u)
    return AdminKeyOut(id=u.id, name=u.name, api_key=key)


@app.post("/api/v1/admin/users/{user_id}/disable", response_model=UserOut)
def admin_disable(user_id: int, me_: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u: raise HTTPException(404, "no existe")
    if u.id == me_.id: raise HTTPException(400, "no puedes desactivarte a ti mismo")
    u.disabled = True
    db.commit(); db.refresh(u)
    return u


@app.post("/api/v1/admin/users/{user_id}/enable", response_model=UserOut)
def admin_enable(user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u: raise HTTPException(404, "no existe")
    u.disabled = False
    db.commit(); db.refresh(u)
    return u


@app.post("/api/v1/admin/users/{user_id}/rotate", response_model=AdminKeyOut)
def admin_rotate(user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u: raise HTTPException(404, "no existe")
    key = generate_api_key()
    u.api_key_hash = hash_key(key)
    db.commit(); db.refresh(u)
    return AdminKeyOut(id=u.id, name=u.name, api_key=key)


@app.patch("/api/v1/admin/users/{user_id}", response_model=UserOut)
def admin_rename(
    user_id: int,
    body: AdminRenameIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if not u: raise HTTPException(404, "no existe")
    if db.query(User).filter(User.name == body.name, User.id != user_id).first():
        raise HTTPException(409, f"nombre '{body.name}' ya en uso")
    u.name = body.name
    db.commit(); db.refresh(u)
    return u


@app.get("/api/v1/admin/users/{user_id}/access")
def admin_access_log(
    user_id: int,
    limit: int = Query(100, ge=1, le=1000),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if not u: raise HTTPException(404, "no existe")
    rows = (
        db.query(AccessLog)
        .filter(AccessLog.user_id == user_id)
        .order_by(AccessLog.id.desc())
        .limit(limit)
        .all()
    )
    distinct_ips = {r.ip for r in rows}
    distinct_devices = {(r.stable_id or r.ua_hash) for r in rows}
    mismatches = [r for r in rows if not r.device_match]
    return {
        "user": {
            "id": u.id, "name": u.name,
            "pinned_ip": u.pinned_ip,
            "pinned_ua_hash": u.pinned_ua_hash,
            "pinned_stable_id": u.pinned_stable_id,
            "pinned_hostname": u.pinned_hostname,
            "pinned_machine_guid": u.pinned_machine_guid,
            "pinned_at": u.pinned_at.isoformat() if u.pinned_at else None,
        },
        "summary": {
            "distinct_ips": len(distinct_ips),
            "distinct_devices": len(distinct_devices),
            "mismatch_count": len(mismatches),
        },
        "recent": [
            {
                "ip": r.ip,
                "user_agent": r.user_agent,
                "ua_hash": r.ua_hash,
                "device_match": r.device_match,
                "path": r.path,
                "at": r.created_at.isoformat(),
                "stable_id": r.stable_id,
                "hostname": r.hostname,
                "machine_guid": r.machine_guid,
                "device_info": r.device_info,
            } for r in rows
        ],
    }


@app.post("/api/v1/admin/users/{user_id}/unpin")
def admin_unpin(user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Borra el pinned device para que la proxima key usada quede pineada."""
    u = db.get(User, user_id)
    if not u: raise HTTPException(404, "no existe")
    u.pinned_ua_hash = None
    u.pinned_ip = None
    u.pinned_at = None
    u.pinned_stable_id = None
    u.pinned_hostname = None
    u.pinned_machine_guid = None
    db.commit()
    return {"ok": True}


@app.delete("/api/v1/admin/users/{user_id}")
def admin_delete(user_id: int, me_: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u: raise HTTPException(404, "no existe")
    if u.id == me_.id: raise HTTPException(400, "no puedes borrarte a ti mismo")
    db.delete(u); db.commit()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000, reload=False)
