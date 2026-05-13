# Albion Market Collector

Sistema **colaborativo** para capturar y analizar datos del mercado de
**Albion Online** en tiempo real. Cada contribuidor corre un sniffer local
que captura el tráfico Photon del cliente del juego (puerto UDP 5056) y lo
sube a un servidor central. La web ofrece búsqueda tipo juego, comparador
de precios entre las 8 ciudades, oportunidades de **venta rápida**
(arbitraje) y **rentabilidad de crafteos** con/sin foco y ciudades bonus.

```
   Contribuidores                          Servidor central
  (N PCs con Albion)                       ┌──────────────────────────────┐
                                           │ FastAPI + SQLite             │
   Albion-Online.exe ── UDP 5056 ─┐        │  POST /api/v1/orders   (key) │
       │                          ▼        │  POST /api/v1/history  (key) │
   simple_sniffer.py ──▶ buffer SQLite ──HTTPS──▶ GET  /api/v1/items      │
       │                              ▲    │  GET  /api/v1/catalog        │
       └─ launcher.py (GUI local)────┘     │  GET  /api/v1/item/{id}      │
                                           │  GET  /api/v1/flips          │
                                           │  GET  /api/v1/crafting       │
                                           │  GET  /            (viewer)  │
                                           │  GET  /admin       (panel)   │
                                           └──────────────┬───────────────┘
                                                          │
                                                Cloudflare Tunnel
                                                          │
                                                https://tu-dominio
```

## Tabla de contenidos

1. [Características](#1-características)
2. [Instalación rápida — contribuidor](#2-instalación-rápida--contribuidor)
3. [Instalación del servidor](#3-instalación-del-servidor)
4. [Exponer el servidor con Cloudflare](#4-exponer-el-servidor-con-cloudflare-tunnel)
5. [Generar catálogo y recetas](#5-generar-catálogo-y-recetas)
6. [Gestión de usuarios y API keys](#6-gestión-de-usuarios-y-api-keys)
7. [La web — vistas](#7-la-web--vistas)
8. [Puerta de contribución](#8-puerta-de-contribución-anti-leech)
9. [Endpoints de la API](#9-endpoints-de-la-api)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Características

- **Captura en tiempo real** de órdenes de venta y compra (incluido Black
  Market) con cantidad, calidad, encantamiento y ciudad.
- **Búsqueda tipo Albion**: sidebar con 13 categorías → subcategorías
  (armas por tipo, armaduras por material, accesorios, consumibles,
  artefactos, monturas, muebles, recursos, granja, libros…) sobre **6215
  items** indexados.
- **Detalle de item**: precios por ciudad para cada combinación de calidad
  (1–5) y encantamiento (0–4). Mejor venta y mejor compra resaltadas.
- **Venta rápida (flips)**: arbitraje entre ciudades — comprar barato en
  una y vender caro en otra, con descuento de fee del mercado (Black
  Market 3%, resto 4.5%).
- **Crafteos**: rentabilidad real por receta sobre **3203 items
  fabricables**, probando todas las combinaciones (ciudad de materiales ×
  ciudad de crafteo × ciudad de venta), con/sin foco y ciudades bonus
  (return rates 15.2 / 24.8 / 43.5 / 53.9 %).
- **Multi-usuario** con API keys hasheadas (SHA-256), tracking de
  dispositivo (MAC + Machine GUID + BIOS serial + hostname) e IP por
  contribuidor.
- **Panel admin web** para crear/renombrar/desactivar/rotar/borrar
  usuarios sin entrar a la CLI.
- **Puerta de contribución**: los usuarios deben aportar ≥ 4000 capturas
  diarias para ver la web. Admin exento. Mantiene la base de datos viva.
- **Launcher gráfico** para contribuidores: introducen URL + API key,
  instalan dependencias con un botón, eligen ciudad y arrancan.

---

## 2. Instalación rápida — contribuidor

### Requisitos
- **Windows 10/11** (Linux/Mac no soportado por dependencia de Npcap).
- **Python 3.11+** ([descargar](https://www.python.org/downloads/) marcando
  "Add Python to PATH").
- **[Npcap](https://npcap.com/#download)** instalado en modo *WinPcap API
  compatible* (es la opción por defecto).
- Cliente de **Albion Online** abierto.
- Permisos de **administrador** (la captura de paquetes lo requiere).

### Pasos
1. Descarga este repo (Code → Download ZIP, o `git clone`).
2. Doble clic en **`client/launcher.bat`**. Saltará UAC, acéptalo.
3. Se abre el navegador en `http://127.0.0.1:7777`.
4. Pega la **URL del servidor** y tu **API key** → *Validar*.
5. Pulsa *Instalar dependencias* (la primera vez tarda 1–2 min).
6. Selecciona tu **ciudad** y pulsa *Iniciar sniffer*.
7. Dentro del juego abre el mercado:
   - **Pestaña Vender** y **Pestaña Comprar** (ambas — la de comprar es
     necesaria para datos de buy orders y para que funcionen los flips).
   - Cambia tier/calidad/encantamiento para poblar más datos.
   - Repite por categorías (armas, armaduras, consumibles, materiales…).
8. Cuando termines, pulsa *Detener* o cierra la ventana del launcher.

El sniffer guarda en local (`market.db` SQLite) y reenvía al servidor
automáticamente. Si el server está caído, los datos se acumulan y se
reenvían cuando vuelva.

### Sin launcher (CLI)
```powershell
pip install -r requirements.txt
$env:ALBION_SERVER_URL = "https://tu-server"
$env:ALBION_API_KEY    = "alb_xxxxxxxxxxxxx"
py scripts\simple_sniffer.py --city 4   # 4 = Martlock, ver --help
```

---

## 3. Instalación del servidor

### Requisitos
- Python 3.11+
- Windows, Linux o macOS

### Pasos
```powershell
# 1. Clona el repo
git clone https://github.com/TUUSUARIO/albion-market-collector.git
cd albion-market-collector

# 2. Instala dependencias del server
py -m pip install -r server/requirements.txt

# 3. Crea tu usuario admin (la PRIMERA vez)
py -m server.admin create-user TU_NOMBRE
#  → imprime la API key una sola vez, GUÁRDALA
py -m server.admin make-admin TU_NOMBRE

# 4. (Opcional) Descarga catálogo de items y recetas si no están
py scripts\fetch_catalog.py
py scripts\fetch_recipes.py

# 5. Arranca el servidor
py start_server.py
#   o sin Cloudflare:
py -m uvicorn server.app:app --host 0.0.0.0 --port 8000
```

- DB en `server/data/server.db` (creada al arranque, migraciones
  automáticas).
- Viewer web: http://localhost:8000
- Panel admin: http://localhost:8000/admin

### `start_server.py`
Lanza simultáneamente:
- **uvicorn** en `0.0.0.0:8000`
- **cloudflared** Quick Tunnel y detecta la URL `trycloudflare.com`

Útil para no tener un dominio aún. Al cerrarse imprime un resumen y
mata los dos procesos.

---

## 4. Exponer el servidor con Cloudflare Tunnel

Si quieres una URL permanente (`https://albion.tu-dominio.com`):

### 4.1 Instalar `cloudflared`
Descarga [`cloudflared.exe`](https://github.com/cloudflare/cloudflared/releases/latest)
y ponlo en el PATH (o en la raíz del proyecto).

### 4.2 Login + tunnel + DNS
```powershell
cloudflared tunnel login                            # abre navegador, elige tu dominio
cloudflared tunnel create albion-market             # apunta el UUID que imprime
cloudflared tunnel route dns albion-market albion.tu-dominio.com
```

### 4.3 Config `%USERPROFILE%\.cloudflared\config.yml`
```yaml
tunnel: albion-market
credentials-file: C:\Users\TU_USER\.cloudflared\<UUID>.json
ingress:
  - hostname: albion.tu-dominio.com
    service: http://localhost:8000
  - service: http_status:404
```

### 4.4 Run
```powershell
cloudflared tunnel run albion-market
# o instalarlo como servicio de Windows:
cloudflared service install
```

### Alternativa: Quick Tunnel (sin dominio)
```powershell
cloudflared tunnel --url http://localhost:8000
```
Imprime una URL `xxx.trycloudflare.com` (cambia en cada reinicio).
`start_server.py` ya hace esto automáticamente.

---

## 5. Generar catálogo y recetas

Los archivos ya están incluidos en el repo
(`server/data/catalog.json` y `recipes.json`). Para regenerarlos con la
última versión de los datos de Albion:

```powershell
py scripts\fetch_catalog.py     # ~15 MB descarga -> server/data/catalog.json (1.3 MB)
py scripts\fetch_recipes.py     # ~17 MB descarga -> server/data/recipes.json (582 KB)
```

Fuente: [ao-data/ao-bin-dumps](https://github.com/ao-data/ao-bin-dumps).
Tras regenerarlos, reinicia el servidor.

---

## 6. Gestión de usuarios y API keys

### Panel web (recomendado)
1. Abre `https://tu-server/admin`.
2. Introduce tu API key (la de un usuario con `is_admin=True`).
3. Desde el panel puedes:
   - **Crear** usuarios (la key emitida se muestra **una sola vez**).
   - **Renombrar** (edita la celda).
   - **Ver accesos** (IP, User-Agent, MAC, machine GUID, hostname,
     historial completo de accesos por usuario).
   - **Desactivar** / **reactivar**.
   - **Rotar key** (invalida la anterior).
   - **Unpin device** (resetea el dispositivo pineado por si cambian de
     PC con tu permiso).
   - **Borrar**.

### CLI
```powershell
py -m server.admin create-user alice           # crea y emite key
py -m server.admin list                        # lista actividad
py -m server.admin disable alice
py -m server.admin enable alice
py -m server.admin rotate-key alice
py -m server.admin make-admin alice            # da acceso al panel /admin
py -m server.admin revoke-admin alice
```

Las keys se guardan **hasheadas con SHA-256**. La key en claro solo se
muestra al crearla o rotarla — guárdala en un gestor de contraseñas.

### Tracking de dispositivo
Cada acceso registra: IP (CF-Connecting-IP / X-Forwarded-For),
User-Agent, hash UA, hostname, MAC, Machine GUID y BIOS serial. La
primera vez que se usa una key, esos valores quedan **pineados**. Si en
un acceso posterior cambian, el panel muestra `DEVICE MISMATCH` y queda
registrado para auditoría.

---

## 7. La web — vistas

### Buscar
Sidebar tipo Albion:
- Buscador texto (matchea nombre español, inglés o ID).
- Chips de tier (T1–T8).
- Árbol de **categorías → subcategorías** con conteo de items.
Click en cualquier item abre el **modal de detalle**.

### Precios recientes
Tabla con filtros clásicos (item / ciudad / tipo offer-request / modo
"precio más bajo" o "todas"). Click en fila → detalle.

### Venta rápida
Arbitraje entre ciudades: el sistema busca items donde
`precio_compra_en_A < precio_venta_en_B - fees`. Filtros: comprar/vender
en ciudad concreta, categoría, tier, margen mínimo absoluto y %,
antigüedad máxima de las órdenes.

### Crafteos
Por defecto **muestra los top 200 más rentables**. Para cada receta
prueba todas las combinaciones (mats × craft × venta). Filtros:
categoría, tier, foco sí/no, modo de venta (pasiva/instantánea), fee de
estación (silver/100 nutrición) y beneficio mínimo. Las ciudades bonus
aparecen marcadas con ⭐ y su return rate.

### Detalle de item (modal)
Imagen + selectores de calidad y encantamiento + tabla de las 8
ciudades con mejor venta y mejor compra simultáneamente. Resalta en
verde la ciudad más barata para comprar y la más cara para vender.

### Contribuciones
Modal accesible desde el header. Ranking diario de contribuidores
ordenado por capturas de hoy. Indica para cada uno si supera o no el
umbral.

---

## 8. Puerta de contribución (anti-leech)

Para evitar que la web se use sin aportar, los **no-admins** necesitan
al menos **`DAILY_CONTRIB_THRESHOLD = 4000` capturas al día** (orders +
history). Por debajo, todos los endpoints de datos devuelven HTTP 403 y
la web muestra una pantalla bloqueante con el progreso `X / 4000` y un
enlace al ranking.

Reset diario: **00:00 UTC**. Para cambiar el umbral, edita
`server/app.py`:
```python
DAILY_CONTRIB_THRESHOLD = 4000
```

---

## 9. Endpoints de la API

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/` | session | Viewer web |
| GET | `/login` | — | Form login |
| GET | `/admin` | session+admin | Panel admin |
| GET | `/health` | — | Health check |
| POST | `/api/v1/session` | (api_key body) | Login → cookie |
| POST | `/api/v1/session/logout` | — | Cierra sesión |
| GET | `/api/v1/me` | any | Usuario actual + contribuciones |
| GET | `/api/v1/contributions` | any | Ranking de contribuciones |
| GET | `/api/v1/cities` | — | Lista de ciudades con datos |
| GET | `/api/v1/stats` | — | Contadores globales |
| GET | `/api/v1/items` | **gate** | Listado con filtros (precios recientes) |
| GET | `/api/v1/catalog` | **gate** | Buscador del catálogo |
| GET | `/api/v1/catalog/categories` | **gate** | Árbol de categorías |
| GET | `/api/v1/item/{id}` | **gate** | Detalle por ciudad (Q+E) |
| GET | `/api/v1/flips` | **gate** | Oportunidades de arbitraje |
| GET | `/api/v1/crafting` | **gate** | Rentabilidad de crafteos |
| POST | `/api/v1/orders` | X-API-Key | Upload de órdenes (batch ≤1000) |
| POST | `/api/v1/history` | X-API-Key | Upload de histórico |
| POST | `/api/v1/gold` | X-API-Key | Upload precio del oro |
| `*` | `/api/v1/admin/users[...]` | admin | CRUD usuarios |

**gate** = requiere sesión + 4000 capturas/día (admin exento).

---

## 10. Troubleshooting

### Cliente

| Síntoma | Causa probable | Solución |
|---|---|---|
| `pkts=0` durante minutos | Npcap no instalado o sin permisos | Instala Npcap modo WinPcap-compat, ejecuta launcher como admin |
| `pkts > 0` pero `orders=0` | Solo abriste la pestaña *Vender* (o ninguna) | Abre *Comprar* y *Vender* en distintas ciudades |
| `Could not find a version that satisfies the requirement psycopg-binary` | Versiones fijadas anticuadas | Esta es la deps del server; el cliente no la necesita. Si insistes, instala manualmente: `pip install scapy psutil click pydantic pydantic-settings pyyaml structlog photon-packet-parser` |
| `HTTP 401: Invalid API key` | Key rotada o mal copiada | Pide la nueva al admin |
| `HTTP 403: User disabled` | Te han desactivado | Habla con el admin |

### Servidor

| Síntoma | Solución |
|---|---|
| `no such column: uploaded` al arrancar sniffer | Tabla SQLite antigua — borra `data/market.db` del cliente |
| `AttributeError: 'str' object has no attribute 'isoformat'` | Estás en una versión antigua, `git pull` |
| Tunnel no levanta (`failed to request quick Tunnel`) | Reintenta. Quick tunnels son inestables. Mejor crea uno permanente |
| Panel admin no carga datos | Asegúrate de tener `is_admin=True`: `py -m server.admin make-admin TU_NOMBRE` |

---

## Licencia

MIT. Datos de Albion Online © Sandbox Interactive — este proyecto solo
captura tráfico del cliente para análisis personal/comunitario, no
modifica el cliente ni viola TOS.
