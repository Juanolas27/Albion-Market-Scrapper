"""Albion Market - Launcher grafico (web local).

Arranca http://127.0.0.1:7777 con UI minima:
  - URL del servidor + API key
  - Boton Instalar dependencias (pip)
  - Selector de ciudad + Iniciar / Detener
  - Logs en vivo

En CADA request al servidor (validacion, subidas del sniffer) se incluye el
header X-Device-Info con fingerprint del PC (MAC, Machine GUID, hostname,
usuario, OS, serial de placa...). El servidor lo registra y detecta cambios
de dispositivo.

Ejecutalo como Administrador (para que el sniffer pueda capturar paquetes).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fingerprint import collect as collect_fp, encode_header as fp_header  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
REQS = ROOT / "requirements.txt"
SNIFFER = ROOT / "scripts" / "simple_sniffer.py"

CITIES = [
    [1, "Thetford"], [2, "Fort Sterling"], [3, "Lymhurst"],
    [4, "Martlock"], [5, "Bridgewatch"], [6, "Caerleon"],
    [7, "Black Market"], [8, "Brecilien"],
]

PORT = int(os.environ.get("ALBION_LAUNCHER_PORT", "7777"))

# Fingerprint del PC (se calcula una sola vez al arrancar).
DEVICE = collect_fp()
DEVICE_HEADER = fp_header(DEVICE)


# =====================================================================
# ESTADO
# =====================================================================

class State:
    def __init__(self):
        self.server_url: str = ""
        self.api_key: str = ""
        self.user_name: str | None = None
        self.validated: bool = False
        self.installing: bool = False
        self.sniffer_running: bool = False
        self.sniffer_proc: subprocess.Popen | None = None
        self.sniffer_city: int | None = None
        self.logs: deque[str] = deque(maxlen=800)

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self.logs.append(line)
        print(line, flush=True)

    def snapshot(self) -> dict:
        return {
            "server_url": self.server_url,
            "user_name": self.user_name,
            "validated": self.validated,
            "installing": self.installing,
            "sniffer_running": self.sniffer_running,
            "sniffer_city": self.sniffer_city,
            "cities": CITIES,
            "logs": list(self.logs)[-200:],
            "device": {
                "hostname": DEVICE.get("hostname"),
                "user": DEVICE.get("user"),
                "os": DEVICE.get("os_system"),
                "stable_id": DEVICE.get("stable_id"),
                "machine_guid": DEVICE.get("machine_guid"),
                "macs": DEVICE.get("macs"),
            },
        }


STATE = State()


# =====================================================================
# LOGICA
# =====================================================================

def validate_key(server_url: str, api_key: str) -> dict:
    req = urllib.request.Request(
        server_url.rstrip("/") + "/api/v1/me",
        headers={
            "X-API-Key": api_key,
            "X-Device-Info": DEVICE_HEADER,
            "User-Agent": f"albion-launcher/{DEVICE.get('hostname','?')}",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def pip_install() -> None:
    STATE.installing = True
    STATE.log("Instalando dependencias (pip install -r requirements.txt)...")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "-r", str(REQS)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                STATE.log(line)
        rc = proc.wait()
        if rc != 0:
            STATE.log(f"ERROR: pip salio con codigo {rc}")
            return
        STATE.log("Dependencias instaladas correctamente.")
    except Exception as e:
        STATE.log(f"ERROR instalando: {e}")
    finally:
        STATE.installing = False


def start_sniffer(city_num: int) -> None:
    if STATE.sniffer_running:
        return
    env = os.environ.copy()
    env["ALBION_SERVER_URL"] = STATE.server_url
    env["ALBION_API_KEY"] = STATE.api_key
    env["ALBION_DEVICE_INFO"] = DEVICE_HEADER
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(SNIFFER), "--city", str(city_num)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace",
            env=env, cwd=str(ROOT),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
    except Exception as e:
        STATE.log(f"ERROR arrancando sniffer: {e}")
        return

    STATE.sniffer_proc = proc
    STATE.sniffer_running = True
    STATE.sniffer_city = city_num
    STATE.log(f"Sniffer arrancado (pid={proc.pid}, ciudad={city_num}).")

    def pump():
        assert proc.stdout is not None
        for line in proc.stdout:
            STATE.log(line.rstrip())
        rc = proc.wait()
        STATE.sniffer_running = False
        STATE.sniffer_city = None
        STATE.log(f"Sniffer terminado (rc={rc}).")

    threading.Thread(target=pump, daemon=True).start()


def stop_sniffer() -> None:
    p = STATE.sniffer_proc
    if not p:
        return
    if p.poll() is None:
        STATE.log("Deteniendo sniffer...")
        try:
            if os.name == "nt":
                p.send_signal(subprocess.signal.CTRL_BREAK_EVENT)
            else:
                p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        except Exception as e:
            STATE.log(f"Error al detener: {e}")
    STATE.sniffer_running = False
    STATE.sniffer_city = None


# =====================================================================
# HTTP HANDLER
# =====================================================================

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            self._json(200, STATE.snapshot())
        elif self.path == "/api/device":
            self._json(200, DEVICE)
        else:
            self.send_error(404)

    def do_POST(self):
        try:
            if self.path == "/api/validate":
                self._validate()
            elif self.path == "/api/install":
                if not STATE.validated:
                    return self._json(403, {"error": "Valida la API key primero."})
                if STATE.installing:
                    return self._json(400, {"error": "Instalacion ya en curso."})
                threading.Thread(target=pip_install, daemon=True).start()
                self._json(202, {"ok": True})
            elif self.path == "/api/start":
                if not STATE.validated:
                    return self._json(403, {"error": "Valida la API key primero."})
                if STATE.sniffer_running:
                    return self._json(400, {"error": "Ya esta corriendo."})
                b = self._read_json()
                try:
                    city = int(b.get("city"))
                except (TypeError, ValueError):
                    return self._json(400, {"error": "Ciudad invalida."})
                if city not in [c[0] for c in CITIES]:
                    return self._json(400, {"error": "Ciudad fuera de rango."})
                threading.Thread(target=start_sniffer, args=(city,), daemon=True).start()
                self._json(200, {"ok": True})
            elif self.path == "/api/stop":
                stop_sniffer()
                self._json(200, {"ok": True})
            elif self.path == "/api/logout":
                STATE.validated = False
                STATE.api_key = ""
                STATE.user_name = None
                STATE.log("Sesion cerrada.")
                self._json(200, {"ok": True})
            else:
                self.send_error(404)
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _validate(self):
        b = self._read_json()
        server_url = (b.get("server_url") or "").strip()
        api_key = (b.get("api_key") or "").strip()
        if not server_url or not api_key:
            return self._json(400, {"error": "Faltan server_url o api_key"})
        try:
            info = validate_key(server_url, api_key)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            return self._json(401, {"error": f"HTTP {e.code}: {detail}"})
        except Exception as e:
            return self._json(502, {"error": f"No se pudo contactar al servidor: {e}"})
        STATE.server_url = server_url.rstrip("/")
        STATE.api_key = api_key
        STATE.user_name = info.get("name")
        STATE.validated = True
        STATE.log(f"API key valida. Bienvenido, {STATE.user_name}.")
        self._json(200, {"ok": True, "name": info.get("name")})


# =====================================================================
# HTML (UI minima: 2 inputs + install + city/start)
# =====================================================================

HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Albion Market - Contribuidor</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         background: #1a1a1a; color: #e0e0e0; margin: 0; padding: 20px;
         max-width: 820px; margin: 0 auto; }
  h1 { color: #ffd700; margin: 0 0 4px; font-size: 22px; }
  .sub { color: #888; font-size: 12px; margin-bottom: 18px; }
  .card { background: #242424; border: 1px solid #333; border-radius: 8px;
          padding: 14px 16px; margin-bottom: 12px; }
  .card h2 { margin: 0 0 10px; font-size: 13px; color: #ffd700;
             text-transform: uppercase; letter-spacing: .5px; }
  label { display: block; font-size: 11px; color: #888;
          text-transform: uppercase; margin: 6px 0 3px; }
  input, select, button {
    background: #1a1a1a; color: #e0e0e0; border: 1px solid #444;
    padding: 8px 11px; border-radius: 4px; font-size: 14px; font-family: inherit;
  }
  input:focus, select:focus { outline: none; border-color: #ffd700; }
  input[type=text], input[type=password] { width: 100%; font-family: monospace; font-size: 13px; }
  button { background: #ffd700; color: #000; cursor: pointer; font-weight: bold;
           border-color: #ffd700; }
  button:hover:not(:disabled) { background: #ffed4e; }
  button:disabled { background: #444; color: #888; border-color: #444; cursor: not-allowed; }
  button.ghost { background: transparent; color: #e0e0e0; border-color: #555; font-weight: normal; }
  button.ghost:hover:not(:disabled) { background: #1a1a1a; }
  button.danger { background: #c64; color: #fff; border-color: #c64; }
  button.danger:hover:not(:disabled) { background: #e85; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .row > * { flex: 0 0 auto; }
  .row > .grow { flex: 1 1 auto; min-width: 140px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
           font-size: 11px; font-weight: bold; }
  .badge.ok { background: #264; color: #afd; }
  .badge.run { background: #553; color: #ffd700; }
  .badge.off { background: #333; color: #aaa; }
  .logs { background: #0d0d0d; border: 1px solid #333; border-radius: 6px;
          font-family: Consolas, monospace; font-size: 12px;
          padding: 10px; height: 220px; overflow-y: auto; white-space: pre-wrap;
          color: #bcd; }
  .err { color: #e66; font-size: 12px; margin-top: 6px; min-height: 14px; }
  .device-grid { display: grid; grid-template-columns: max-content 1fr;
                 gap: 2px 12px; font-size: 12px; color: #aaa; }
  .device-grid b { color: #ffd700; font-weight: normal; }
  .device-grid code { color: #9cf; font-family: monospace; font-size: 11px;
                      word-break: break-all; }
  details summary { cursor: pointer; color: #888; font-size: 12px;
                    user-select: none; }
  details[open] summary { color: #ccc; margin-bottom: 8px; }
</style>
</head>
<body>

<h1>Albion Market &mdash; Contribuidor</h1>
<div class="sub">
  Introduce la URL del servidor y tu API key. Despues instala las dependencias
  (solo 1a vez), elige tu ciudad y pulsa Iniciar.
</div>

<!-- CONEXION -->
<div class="card">
  <h2>Conexion <span id="conn-badge"></span></h2>
  <label>URL del servidor</label>
  <input type="text" id="server-url" placeholder="https://xxxx.trycloudflare.com" value="https://">
  <label>API key</label>
  <input type="password" id="api-key" placeholder="alb_...">
  <div class="row" style="margin-top:10px">
    <button id="btn-validate" onclick="doValidate()">Validar</button>
    <button class="ghost" id="btn-logout" onclick="doLogout()" style="display:none">Desconectar</button>
  </div>
  <div id="err-conn" class="err"></div>
</div>

<!-- DEPENDENCIAS + CONTROL -->
<div class="card" id="ops-card" style="opacity:.45">
  <h2>Control <span id="op-badge"></span></h2>
  <div class="row" style="margin-bottom:8px">
    <button id="btn-install" onclick="doInstall()" disabled>Instalar dependencias</button>
    <span id="install-status" style="color:#9cf;font-size:12px"></span>
  </div>
  <div class="row">
    <label style="margin:0;align-self:center">Ciudad</label>
    <select id="city" class="grow" disabled></select>
    <button id="btn-start" onclick="doStart()" disabled>Iniciar</button>
    <button id="btn-stop" class="danger" onclick="doStop()" disabled>Detener</button>
  </div>
  <div id="err-ops" class="err"></div>
</div>

<!-- DISPOSITIVO -->
<div class="card">
  <details>
    <summary>Identificadores que este PC envia al servidor (click para ver)</summary>
    <div id="device-info" class="device-grid"></div>
    <div style="color:#666;font-size:11px;margin-top:10px">
      Estos datos viajan en el header X-Device-Info en cada peticion al servidor.
      El admin los usa para verificar que siempre subes desde el mismo PC.
    </div>
  </details>
</div>

<!-- LOGS -->
<div class="card">
  <h2>Logs</h2>
  <div id="logs" class="logs">(esperando...)</div>
</div>

<script>
const $ = id => document.getElementById(id);

async function api(method, path, body) {
  const opts = { method, headers: {'Content-Type':'application/json'} };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  const text = await r.text();
  const data = text ? JSON.parse(text) : {};
  if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}

async function doValidate() {
  $('err-conn').textContent = '';
  const server_url = $('server-url').value.trim();
  const api_key = $('api-key').value.trim();
  $('btn-validate').disabled = true;
  try {
    await api('POST', '/api/validate', { server_url, api_key });
    localStorage.setItem('alb_server', server_url);
  } catch (e) {
    $('err-conn').textContent = e.message;
  } finally {
    $('btn-validate').disabled = false;
    refresh();
  }
}

async function doLogout() {
  await api('POST', '/api/logout');
  $('api-key').value = '';
  refresh();
}

async function doInstall() {
  $('btn-install').disabled = true;
  try { await api('POST', '/api/install'); }
  catch (e) { alert(e.message); $('btn-install').disabled = false; }
}

async function doStart() {
  $('err-ops').textContent = '';
  try { await api('POST', '/api/start', { city: parseInt($('city').value,10) }); }
  catch (e) { $('err-ops').textContent = e.message; }
}

async function doStop() {
  try { await api('POST', '/api/stop'); }
  catch (e) { alert(e.message); }
}

function renderCities(cs) {
  const sel = $('city');
  if (sel.options.length === cs.length) return;
  sel.innerHTML = cs.map(c => `<option value="${c[0]}">${c[0]}. ${c[1]}</option>`).join('');
}

function renderDevice(d) {
  if (!d) return;
  $('device-info').innerHTML = `
    <b>Hostname</b><code>${esc(d.hostname || '-')}</code>
    <b>Usuario</b><code>${esc(d.user || '-')}</code>
    <b>OS</b><code>${esc(d.os || '-')}</code>
    <b>Machine GUID</b><code>${esc(d.machine_guid || '-')}</code>
    <b>MACs</b><code>${esc((d.macs || []).join(', ') || '-')}</code>
    <b>Stable ID</b><code>${esc(d.stable_id || '-')}</code>`;
}

function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

async function refresh() {
  let s;
  try { s = await api('GET', '/api/status'); } catch { return; }
  renderCities(s.cities);
  renderDevice(s.device);

  // Conexion
  if (s.validated) {
    $('conn-badge').innerHTML = `<span class="badge ok">${esc(s.user_name)}</span>`;
    $('btn-validate').textContent = 'Re-validar';
    $('btn-logout').style.display = '';
    $('server-url').value = s.server_url || $('server-url').value;
  } else {
    $('conn-badge').innerHTML = '';
    $('btn-validate').textContent = 'Validar';
    $('btn-logout').style.display = 'none';
    const saved = localStorage.getItem('alb_server');
    if (saved && $('server-url').value === 'https://') $('server-url').value = saved;
  }

  // Control
  const card = $('ops-card');
  card.style.opacity = s.validated ? '1' : '.45';
  $('btn-install').disabled = !s.validated || s.installing;
  $('install-status').textContent = s.installing ? 'Instalando, mira logs...' : '';

  if (!s.validated) {
    $('city').disabled = true;
    $('btn-start').disabled = true;
    $('btn-stop').disabled = true;
    $('op-badge').innerHTML = '';
  } else if (s.sniffer_running) {
    $('city').disabled = true;
    $('btn-start').disabled = true;
    $('btn-stop').disabled = false;
    $('op-badge').innerHTML = `<span class="badge run">corriendo ciudad=${s.sniffer_city}</span>`;
    $('city').value = s.sniffer_city;
  } else {
    $('city').disabled = false;
    $('btn-start').disabled = false;
    $('btn-stop').disabled = true;
    $('op-badge').innerHTML = '<span class="badge off">detenido</span>';
  }

  // Logs
  const el = $('logs');
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  el.textContent = (s.logs && s.logs.length) ? s.logs.join('\n') : '(sin actividad aun)';
  if (atBottom) el.scrollTop = el.scrollHeight;
}

setInterval(refresh, 1500);
refresh();
</script>
</body>
</html>
"""


# =====================================================================
# MAIN
# =====================================================================

def main():
    STATE.log(f"Launcher escuchando en http://127.0.0.1:{PORT}")
    STATE.log(f"Device stable_id={DEVICE.get('stable_id')}")
    try:
        webbrowser.open(f"http://127.0.0.1:{PORT}")
    except Exception:
        pass
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        STATE.log("Cerrando launcher...")
        stop_sniffer()


if __name__ == "__main__":
    main()
