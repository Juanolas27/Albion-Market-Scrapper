"""
Web viewer para la BD SQLite del sniffer standalone.

Uso:
  py scripts/simple_web.py
  Abre http://localhost:5000
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify, render_template_string, request

DB_PATH = Path(__file__).parent.parent / "data" / "market.db"
SILVER_DIVISOR = 10000

CITY_NAMES = {
    3000: "Thetford", 3002: "Fort Sterling", 3003: "Lymhurst",
    3004: "Martlock", 3005: "Bridgewatch", 3008: "Caerleon",
    3013: "Black Market", 4002: "Brecilien",
}

app = Flask(__name__)


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


INDEX_HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Albion Market Viewer</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         background: #1a1a1a; color: #e0e0e0; margin: 0; padding: 20px; }
  h1 { color: #ffd700; margin: 0 0 10px; }
  .stats { display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }
  .stat { background: #2a2a2a; padding: 12px 18px; border-radius: 6px;
          border-left: 3px solid #ffd700; }
  .stat .label { font-size: 11px; color: #888; text-transform: uppercase; }
  .stat .value { font-size: 20px; font-weight: bold; color: #fff; }
  .filters { display: flex; gap: 10px; margin-bottom: 15px;
             flex-wrap: wrap; align-items: center; }
  input, select, button { background: #2a2a2a; color: #e0e0e0;
      border: 1px solid #444; padding: 8px 12px; border-radius: 4px; font-size: 14px; }
  input:focus, select:focus { outline: none; border-color: #ffd700; }
  button { background: #ffd700; color: #000; cursor: pointer;
      font-weight: bold; border-color: #ffd700; }
  button:hover { background: #ffed4e; }
  table { width: 100%; border-collapse: collapse;
      background: #2a2a2a; border-radius: 6px; overflow: hidden; }
  th { background: #333; color: #ffd700; text-align: left;
      padding: 10px; font-size: 12px; text-transform: uppercase;
      cursor: pointer; user-select: none; }
  th:hover { background: #3a3a3a; }
  th.sorted-asc::after { content: " ▲"; }
  th.sorted-desc::after { content: " ▼"; }
  td { padding: 8px 10px; border-top: 1px solid #333; font-size: 13px;
       vertical-align: middle; }
  tr:hover td { background: #333; }
  .item-img { width: 40px; height: 40px; vertical-align: middle;
      margin-right: 8px; image-rendering: pixelated; }
  .item-cell { display: flex; align-items: center; }
  .price { color: #ffd700; font-weight: bold; text-align: right; }
  .amount { text-align: right; color: #6cf; }
  .enchant { color: #f96; font-weight: bold; }
  .city { color: #9c9; }
  .time { color: #888; font-size: 11px; }
  .loading { text-align: center; padding: 40px; color: #888; }
  .empty { text-align: center; padding: 40px; color: #666; }
  .pagination { margin-top: 15px; display: flex; gap: 10px; align-items: center; }
</style>
</head>
<body>
  <h1>Albion Market Viewer (SQLite)</h1>

  <div class="stats">
    <div class="stat"><div class="label">Items unicos</div><div class="value" id="stat-unique">-</div></div>
    <div class="stat"><div class="label">Total ordenes</div><div class="value" id="stat-orders">-</div></div>
    <div class="stat"><div class="label">Mostrando</div><div class="value" id="stat-shown">-</div></div>
    <div class="stat"><div class="label">Ultima captura</div><div class="value" id="stat-latest">-</div></div>
  </div>

  <div class="filters">
    <input type="text" id="f-item" placeholder="Buscar item" style="width:220px">
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
      <option value="lowest">Precio mas bajo</option>
      <option value="all">Todas</option>
    </select>
    <button onclick="loadData()">Actualizar</button>
    <label><input type="checkbox" id="auto"> Auto 10s</label>
  </div>

  <table>
    <thead><tr>
      <th data-sort="item_albion_id">Item</th>
      <th data-sort="quality_level">Q</th>
      <th data-sort="enchantment_level">E</th>
      <th data-sort="unit_price_silver" style="text-align:right">Precio</th>
      <th data-sort="amount" style="text-align:right">Cant</th>
      <th data-sort="city">Ciudad</th>
      <th data-sort="captured_at">Capturado</th>
    </tr></thead>
    <tbody id="tbody">
      <tr><td colspan="7" class="loading">Cargando...</td></tr>
    </tbody>
  </table>

  <div class="pagination">
    <button onclick="page(-1)">&laquo;</button>
    <span id="page-info">1</span>
    <button onclick="page(1)">&raquo;</button>
  </div>

<script>
let data = [], sortKey='item_albion_id', sortAsc=true, p=0, PS=100, timer=null;

async function loadCities() {
  const r = await fetch('/api/cities');
  const xs = await r.json();
  const sel = document.getElementById('f-city');
  for (const c of xs) { const o=document.createElement('option'); o.value=c; o.textContent=c; sel.appendChild(o); }
}

async function loadData() {
  const q = new URLSearchParams({
    item: document.getElementById('f-item').value,
    tier: document.getElementById('f-tier').value,
    city: document.getElementById('f-city').value,
    type: document.getElementById('f-type').value,
    mode: document.getElementById('f-mode').value,
  });
  document.getElementById('tbody').innerHTML = '<tr><td colspan="7" class="loading">Cargando...</td></tr>';
  const r = await fetch('/api/items?' + q);
  const d = await r.json();
  data = d.rows;
  document.getElementById('stat-unique').textContent = d.stats.unique.toLocaleString();
  document.getElementById('stat-orders').textContent = d.stats.total.toLocaleString();
  document.getElementById('stat-latest').textContent = d.stats.latest || '-';
  p = 0;
  render();
}

function render() {
  const tbody = document.getElementById('tbody');
  const sorted = [...data].sort((a,b)=>{
    let av=a[sortKey], bv=b[sortKey];
    if (typeof av==='string') { av=av.toLowerCase(); bv=(bv||'').toLowerCase(); }
    return av<bv?(sortAsc?-1:1):av>bv?(sortAsc?1:-1):0;
  });
  const slice = sorted.slice(p*PS, (p+1)*PS);
  document.getElementById('stat-shown').textContent = `${slice.length}/${sorted.length}`;
  document.getElementById('page-info').textContent = `${p+1}/${Math.max(1,Math.ceil(sorted.length/PS))}`;
  if (!slice.length) { tbody.innerHTML='<tr><td colspan="7" class="empty">Sin datos</td></tr>'; return; }
  tbody.innerHTML = slice.map(r=>`
    <tr>
      <td><div class="item-cell">
        <img class="item-img" src="${img(r.item_albion_id,r.quality_level,r.enchantment_level)}" loading="lazy" onerror="this.style.opacity=0.2">
        ${esc(r.item_albion_id)}
      </div></td>
      <td>${r.quality_level}</td>
      <td class="enchant">${r.enchantment_level}</td>
      <td class="price">${(r.unit_price_silver/10000).toLocaleString('es-ES',{maximumFractionDigits:2})}</td>
      <td class="amount">${r.amount.toLocaleString()}</td>
      <td class="city">${esc(r.city)}</td>
      <td class="time">${(r.captured_at||'').replace('T',' ').slice(0,19)}</td>
    </tr>`).join('');
  document.querySelectorAll('th').forEach(th=>{
    th.classList.remove('sorted-asc','sorted-desc');
    if (th.dataset.sort===sortKey) th.classList.add(sortAsc?'sorted-asc':'sorted-desc');
  });
}

function img(id,q,e){const s=e>0?`@${e}`:'';return `https://render.albiononline.com/v1/item/${id}${s}.png?quality=${q}`;}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function page(d){const m=Math.ceil(data.length/PS)-1; p=Math.max(0,Math.min(m,p+d)); render();}

document.querySelectorAll('th').forEach(th=>th.addEventListener('click',()=>{
  const k=th.dataset.sort; if(!k) return;
  if (sortKey===k) sortAsc=!sortAsc; else { sortKey=k; sortAsc=true; }
  render();
}));
document.getElementById('f-item').addEventListener('input',()=>{clearTimeout(window._t); window._t=setTimeout(loadData,300);});
['f-tier','f-city','f-type','f-mode'].forEach(id=>document.getElementById(id).addEventListener('change',loadData));
document.getElementById('auto').addEventListener('change',e=>{
  if (e.target.checked) timer=setInterval(loadData,10000); else clearInterval(timer);
});

loadCities().then(loadData);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/api/cities")
def api_cities():
    if not DB_PATH.exists():
        return jsonify([])
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT city_id FROM market_orders ORDER BY city_id").fetchall()
    conn.close()
    return jsonify([CITY_NAMES.get(r[0], str(r[0])) for r in rows])


@app.route("/api/items")
def api_items():
    if not DB_PATH.exists():
        return jsonify({"rows": [], "stats": {"unique": 0, "total": 0, "latest": None}})

    item = request.args.get("item", "").strip()
    tier = request.args.get("tier", "").strip()
    city = request.args.get("city", "").strip()
    auc = request.args.get("type", "").strip()
    mode = request.args.get("mode", "lowest").strip()

    where = []
    params: list = []

    if auc:
        where.append("auction_type = ?")
        params.append(auc)
    if item:
        where.append("item_albion_id LIKE ?")
        params.append(f"%{item}%")
    if tier:
        where.append("item_albion_id LIKE ?")
        params.append(f"{tier}_%")
    if city:
        cid = next((k for k, v in CITY_NAMES.items() if v == city), None)
        if cid is not None:
            where.append("city_id = ?")
            params.append(cid)

    wh = " AND ".join(where) if where else "1=1"

    if mode == "lowest":
        direction = "DESC" if auc == "request" else "ASC"
        query = f"""
            WITH ranked AS (
                SELECT item_albion_id, quality_level, enchantment_level,
                       unit_price_silver, amount, city_id, captured_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY item_albion_id, quality_level, enchantment_level, city_id, auction_type
                           ORDER BY unit_price_silver {direction}
                       ) AS rn
                FROM market_orders WHERE {wh}
            )
            SELECT item_albion_id, quality_level, enchantment_level,
                   unit_price_silver, amount, city_id, captured_at
            FROM ranked WHERE rn = 1
            ORDER BY item_albion_id
            LIMIT 5000
        """
    else:
        query = f"""
            SELECT item_albion_id, quality_level, enchantment_level,
                   unit_price_silver, amount, city_id, captured_at
            FROM market_orders WHERE {wh}
            ORDER BY captured_at DESC
            LIMIT 5000
        """

    conn = get_conn()
    rows = conn.execute(query, params).fetchall()
    unique = conn.execute("SELECT COUNT(DISTINCT item_albion_id) FROM market_orders").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM market_orders").fetchone()[0]
    latest = conn.execute("SELECT MAX(captured_at) FROM market_orders").fetchone()[0]
    conn.close()

    result = [{
        "item_albion_id": r["item_albion_id"],
        "quality_level": r["quality_level"],
        "enchantment_level": r["enchantment_level"],
        "unit_price_silver": r["unit_price_silver"],
        "amount": r["amount"],
        "city": CITY_NAMES.get(r["city_id"], str(r["city_id"])),
        "captured_at": r["captured_at"],
    } for r in rows]

    return jsonify({
        "rows": result,
        "stats": {
            "unique": unique or 0,
            "total": total or 0,
            "latest": (latest or "").replace("T", " ")[:19] if latest else None,
        },
    })


if __name__ == "__main__":
    print("=" * 60)
    print(f"  Albion Market Viewer (SQLite)")
    print(f"  BD: {DB_PATH}")
    print(f"  http://localhost:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False)
