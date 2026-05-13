"""
Albion Market Web Viewer
========================
Interfaz web para ver todos los items escaneados del mercado.

Uso:
  py scripts/web_app.py
  Abre: http://localhost:5000

Endpoints:
  /              -> tabla con filtros
  /api/items     -> JSON con todos los items
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify, render_template_string, request
from sqlalchemy import text

from albion_capture.core.config import load_config
from albion_capture.core.database import create_db_engine
from albion_capture.photon.operations import CITY_NAMES

SILVER_DIVISOR = 10000

app = Flask(__name__)
engine = create_db_engine(load_config().database)


INDEX_HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Albion Market Viewer</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, Segoe UI, Roboto, sans-serif;
    background: #1a1a1a; color: #e0e0e0;
    margin: 0; padding: 20px;
  }
  h1 { color: #ffd700; margin: 0 0 10px; }
  .stats {
    display: flex; gap: 20px; margin-bottom: 20px;
    flex-wrap: wrap;
  }
  .stat {
    background: #2a2a2a; padding: 12px 18px;
    border-radius: 6px; border-left: 3px solid #ffd700;
  }
  .stat .label { font-size: 11px; color: #888; text-transform: uppercase; }
  .stat .value { font-size: 20px; font-weight: bold; color: #fff; }
  .filters {
    display: flex; gap: 10px; margin-bottom: 15px;
    flex-wrap: wrap; align-items: center;
  }
  input, select, button {
    background: #2a2a2a; color: #e0e0e0;
    border: 1px solid #444; padding: 8px 12px;
    border-radius: 4px; font-size: 14px;
  }
  input:focus, select:focus { outline: none; border-color: #ffd700; }
  button {
    background: #ffd700; color: #000; cursor: pointer;
    font-weight: bold; border-color: #ffd700;
  }
  button:hover { background: #ffed4e; }
  table {
    width: 100%; border-collapse: collapse;
    background: #2a2a2a; border-radius: 6px; overflow: hidden;
  }
  th {
    background: #333; color: #ffd700; text-align: left;
    padding: 10px; font-size: 12px; text-transform: uppercase;
    cursor: pointer; user-select: none;
  }
  th:hover { background: #3a3a3a; }
  th.sorted-asc::after { content: " ▲"; }
  th.sorted-desc::after { content: " ▼"; }
  td { padding: 8px 10px; border-top: 1px solid #333; font-size: 13px; vertical-align: middle; }
  tr:hover td { background: #333; }
  .item-img { width: 40px; height: 40px; vertical-align: middle; margin-right: 8px; image-rendering: pixelated; }
  .item-cell { display: flex; align-items: center; }
  .price { color: #ffd700; font-weight: bold; text-align: right; }
  .amount { text-align: right; color: #6cf; }
  .quality-1 { color: #aaa; }
  .quality-2 { color: #6c6; }
  .quality-3 { color: #6cf; }
  .quality-4 { color: #c6f; }
  .quality-5 { color: #fc6; }
  .enchant { color: #f96; font-weight: bold; }
  .city { color: #9c9; }
  .time { color: #888; font-size: 11px; }
  .loading { text-align: center; padding: 40px; color: #888; }
  .empty { text-align: center; padding: 40px; color: #666; }
  .pagination { margin-top: 15px; display: flex; gap: 10px; align-items: center; }
</style>
</head>
<body>
  <h1>Albion Market Viewer</h1>

  <div class="stats" id="stats">
    <div class="stat"><div class="label">Items unicos</div><div class="value" id="stat-unique">-</div></div>
    <div class="stat"><div class="label">Total ordenes</div><div class="value" id="stat-orders">-</div></div>
    <div class="stat"><div class="label">Mostrando</div><div class="value" id="stat-shown">-</div></div>
    <div class="stat"><div class="label">Ultima captura</div><div class="value" id="stat-latest">-</div></div>
  </div>

  <div class="filters">
    <input type="text" id="f-item" placeholder="Buscar item (ej: BAG, SWORD)" style="width:240px">
    <select id="f-tier">
      <option value="">Tier (todos)</option>
      <option>T1</option><option>T2</option><option>T3</option><option>T4</option>
      <option>T5</option><option>T6</option><option>T7</option><option>T8</option>
    </select>
    <select id="f-city">
      <option value="">Ciudad (todas)</option>
    </select>
    <select id="f-type">
      <option value="">Todo</option>
      <option value="offer">Ventas</option>
      <option value="request">Compras</option>
    </select>
    <select id="f-mode">
      <option value="lowest">Solo precio mas bajo</option>
      <option value="all">Todas las ordenes</option>
    </select>
    <button onclick="loadData()">Actualizar</button>
    <label><input type="checkbox" id="auto-refresh"> Auto (10s)</label>
  </div>

  <table id="tbl">
    <thead><tr>
      <th data-sort="item_albion_id">Item</th>
      <th data-sort="quality_level">Q</th>
      <th data-sort="enchantment_level">E</th>
      <th data-sort="unit_price_silver" style="text-align:right">Precio</th>
      <th data-sort="amount" style="text-align:right">Cant</th>
      <th data-sort="city_id">Ciudad</th>
      <th data-sort="captured_at">Capturado</th>
    </tr></thead>
    <tbody id="tbody">
      <tr><td colspan="7" class="loading">Cargando...</td></tr>
    </tbody>
  </table>

  <div class="pagination">
    <button onclick="changePage(-1)">&laquo; Anterior</button>
    <span id="page-info">Pag 1</span>
    <button onclick="changePage(1)">Siguiente &raquo;</button>
  </div>

<script>
let allData = [];
let sortKey = 'item_albion_id';
let sortAsc = true;
let page = 0;
const PAGE_SIZE = 100;
let autoTimer = null;

async function loadCities() {
  const r = await fetch('/api/cities');
  const cities = await r.json();
  const sel = document.getElementById('f-city');
  for (const c of cities) {
    const o = document.createElement('option');
    o.value = c; o.textContent = c;
    sel.appendChild(o);
  }
}

async function loadData() {
  const params = new URLSearchParams({
    item: document.getElementById('f-item').value,
    tier: document.getElementById('f-tier').value,
    city: document.getElementById('f-city').value,
    type: document.getElementById('f-type').value,
    mode: document.getElementById('f-mode').value,
  });
  document.getElementById('tbody').innerHTML = '<tr><td colspan="7" class="loading">Cargando...</td></tr>';
  const r = await fetch('/api/items?' + params);
  const data = await r.json();
  allData = data.rows;

  document.getElementById('stat-unique').textContent = data.stats.unique.toLocaleString();
  document.getElementById('stat-orders').textContent = data.stats.total.toLocaleString();
  document.getElementById('stat-latest').textContent = data.stats.latest || '-';
  page = 0;
  render();
}

function render() {
  const tbody = document.getElementById('tbody');
  const sorted = [...allData].sort((a, b) => {
    let av = a[sortKey], bv = b[sortKey];
    if (typeof av === 'string') { av = av.toLowerCase(); bv = (bv||'').toLowerCase(); }
    if (av < bv) return sortAsc ? -1 : 1;
    if (av > bv) return sortAsc ? 1 : -1;
    return 0;
  });

  const slice = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  document.getElementById('stat-shown').textContent = `${slice.length} / ${sorted.length}`;
  document.getElementById('page-info').textContent = `Pag ${page + 1} / ${Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))}`;

  if (slice.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">Sin datos</td></tr>';
    return;
  }

  tbody.innerHTML = slice.map(r => `
    <tr>
      <td><div class="item-cell">
        <img class="item-img" src="${itemImg(r.item_albion_id, r.quality_level, r.enchantment_level)}"
             loading="lazy" onerror="this.style.opacity=0.2">
        ${escapeHtml(r.item_albion_id)}
      </div></td>
      <td class="quality-${r.quality_level}">${r.quality_level}</td>
      <td class="enchant">${r.enchantment_level}</td>
      <td class="price">${formatPrice(r.unit_price_silver)}</td>
      <td class="amount">${r.amount.toLocaleString()}</td>
      <td class="city">${escapeHtml(r.city)}</td>
      <td class="time">${formatTime(r.captured_at)}</td>
    </tr>
  `).join('');

  document.querySelectorAll('th').forEach(th => {
    th.classList.remove('sorted-asc', 'sorted-desc');
    if (th.dataset.sort === sortKey) {
      th.classList.add(sortAsc ? 'sorted-asc' : 'sorted-desc');
    }
  });
}

function itemImg(id, q, e) {
  // API oficial de Albion: render.albiononline.com
  // Encantamientos: T4_BAG@1, T4_BAG@2, etc.
  const suffix = e > 0 ? `@${e}` : '';
  return `https://render.albiononline.com/v1/item/${id}${suffix}.png?quality=${q}`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function formatPrice(v) {
  return (v / 10000).toLocaleString('es-ES', {minimumFractionDigits: 0, maximumFractionDigits: 2});
}
function formatTime(s) {
  if (!s) return '-';
  return s.replace('T', ' ').slice(0, 19);
}
function changePage(d) {
  const max = Math.ceil(allData.length / PAGE_SIZE) - 1;
  page = Math.max(0, Math.min(max, page + d));
  render();
}

document.querySelectorAll('th').forEach(th => {
  th.addEventListener('click', () => {
    const k = th.dataset.sort;
    if (!k) return;
    if (sortKey === k) sortAsc = !sortAsc;
    else { sortKey = k; sortAsc = true; }
    render();
  });
});

document.getElementById('f-item').addEventListener('input', () => {
  clearTimeout(window._t);
  window._t = setTimeout(loadData, 300);
});
['f-tier','f-city','f-type','f-mode'].forEach(id => {
  document.getElementById(id).addEventListener('change', loadData);
});
document.getElementById('auto-refresh').addEventListener('change', e => {
  if (e.target.checked) autoTimer = setInterval(loadData, 10000);
  else clearInterval(autoTimer);
});

loadCities().then(loadData);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/api/debug")
def api_debug():
    """Diagnostico: cuenta filas, tipos, ciudades, tiempos."""
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM market_orders")).scalar()
        by_type = conn.execute(text(
            "SELECT auction_type, COUNT(*) FROM market_orders GROUP BY auction_type"
        )).fetchall()
        by_city = conn.execute(text(
            "SELECT city_id, COUNT(*) FROM market_orders GROUP BY city_id"
        )).fetchall()
        sample = conn.execute(text(
            "SELECT item_albion_id, auction_type, unit_price_silver, city_id, captured_at "
            "FROM market_orders ORDER BY captured_at DESC LIMIT 5"
        )).fetchall()
    return jsonify({
        "total": total,
        "by_type": [(t, c) for t, c in by_type],
        "by_city": [(CITY_NAMES.get(cid, str(cid)), c) for cid, c in by_city],
        "sample": [list(map(str, r)) for r in sample],
    })


@app.route("/api/cities")
def api_cities():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT city_id FROM market_orders ORDER BY city_id"
        )).fetchall()
    cities = [CITY_NAMES.get(r[0], str(r[0])) for r in rows]
    return jsonify(cities)


@app.route("/api/items")
def api_items():
    item = request.args.get("item", "").strip()
    tier = request.args.get("tier", "").strip()
    city = request.args.get("city", "").strip()
    auc_type = request.args.get("type", "").strip()
    mode = request.args.get("mode", "lowest").strip()

    conditions = []
    params: dict = {}

    if auc_type:
        conditions.append("auction_type = :auc_type")
        params["auc_type"] = auc_type
    if item:
        conditions.append("item_albion_id ILIKE :item_filter")
        params["item_filter"] = f"%{item}%"
    if tier:
        conditions.append("item_albion_id LIKE :tier_filter")
        params["tier_filter"] = f"{tier}_%"
    if city:
        city_id = next((k for k, v in CITY_NAMES.items() if v == city), None)
        if city_id is not None:
            conditions.append("city_id = :city_id")
            params["city_id"] = city_id

    where = " AND ".join(conditions) if conditions else "1=1"

    if mode == "lowest":
        order_dir = "DESC" if auc_type == "request" else "ASC"
        query = text(f"""
            WITH ranked AS (
                SELECT item_albion_id, quality_level, enchantment_level,
                       unit_price_silver, amount, city_id, captured_at, auction_type,
                       ROW_NUMBER() OVER (
                           PARTITION BY item_albion_id, quality_level, enchantment_level, city_id, auction_type
                           ORDER BY unit_price_silver {order_dir}
                       ) AS rn
                FROM market_orders WHERE {where}
            )
            SELECT item_albion_id, quality_level, enchantment_level,
                   unit_price_silver, amount, city_id, captured_at
            FROM ranked WHERE rn = 1
            ORDER BY item_albion_id
            LIMIT 5000
        """)
    else:
        query = text(f"""
            SELECT item_albion_id, quality_level, enchantment_level,
                   unit_price_silver, amount, city_id, captured_at
            FROM market_orders WHERE {where}
            ORDER BY captured_at DESC
            LIMIT 5000
        """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).fetchall()
        unique = conn.execute(text(
            "SELECT COUNT(DISTINCT item_albion_id) FROM market_orders WHERE auction_type='offer'"
        )).scalar() or 0
        total = conn.execute(text(
            "SELECT COUNT(*) FROM market_orders"
        )).scalar() or 0
        latest = conn.execute(text(
            "SELECT MAX(captured_at) FROM market_orders"
        )).scalar()

    result = [{
        "item_albion_id": r[0],
        "quality_level": r[1],
        "enchantment_level": r[2],
        "unit_price_silver": r[3],
        "amount": r[4],
        "city": CITY_NAMES.get(r[5], str(r[5])),
        "city_id": r[5],
        "captured_at": r[6].isoformat() if r[6] else None,
    } for r in rows]

    return jsonify({
        "rows": result,
        "stats": {
            "unique": unique,
            "total": total,
            "latest": str(latest)[:19] if latest else None,
        },
    })


if __name__ == "__main__":
    print("=" * 60)
    print("  Albion Market Web Viewer")
    print("=" * 60)
    print("  http://localhost:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)
