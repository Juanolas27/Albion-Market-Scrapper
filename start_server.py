"""Supervisor: arranca uvicorn + cloudflared en un solo comando.

Uso:
  py start_server.py                   -> Quick Tunnel (URL efimera)
  py start_server.py --tunnel NAME     -> Named Tunnel con config local
  py start_server.py --no-tunnel       -> solo servidor local (sin cloudflared)

Ctrl+C detiene ambos procesos limpiamente.
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLOUDFLARED = ROOT / "cloudflared.exe"
CONFIG_YML = ROOT / "cloudflared-config.yml"

QUICK_URL_RE = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")


class ProcSupervisor:
    def __init__(self):
        self.procs: list[tuple[str, subprocess.Popen]] = []
        self.public_url: str | None = None
        self._url_lock = threading.Lock()
        self._stopping = False

    # -- arranque ------------------------------------------------------

    def spawn(self, name: str, cmd: list[str], cwd: Path | None = None) -> subprocess.Popen:
        print(f"[supervisor] arrancando {name}: {' '.join(cmd)}")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd or ROOT),
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        self.procs.append((name, proc))
        threading.Thread(target=self._pump, args=(name, proc), daemon=True).start()
        return proc

    def _pump(self, name: str, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            print(f"[{name}] {line}")
            # detecta Quick Tunnel URL
            if name == "cloudflared" and not self.public_url:
                m = QUICK_URL_RE.search(line)
                if m:
                    with self._url_lock:
                        self.public_url = m.group(0)
                    self._banner()

        rc = proc.wait()
        if not self._stopping:
            print(f"[supervisor] !! {name} termino con rc={rc} -- parando todo")
            self.stop()

    # -- banner --------------------------------------------------------

    def _banner(self) -> None:
        u = self.public_url
        if not u:
            return
        line = "=" * 78
        print()
        print("\033[93m" + line)
        print("  URL PUBLICA:  " + u)
        print("  Viewer:       " + u + "/")
        print("  Panel admin:  " + u + "/admin")
        print(line + "\033[0m")
        print("  Pasa esta URL a los contribuidores (va en el launcher).")
        print("  NOTA: Quick Tunnel cambia de URL en cada reinicio.")
        print()

    # -- parada --------------------------------------------------------

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        print("\n[supervisor] deteniendo procesos...")
        for name, proc in self.procs:
            if proc.poll() is None:
                try:
                    if os.name == "nt":
                        proc.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        proc.terminate()
                except Exception:
                    pass
        # da 5s para cierre limpio
        deadline = time.time() + 5
        for name, proc in self.procs:
            remaining = max(0, deadline - time.time())
            try:
                proc.wait(timeout=remaining if remaining > 0 else 0.1)
            except subprocess.TimeoutExpired:
                print(f"[supervisor] forzando kill de {name}")
                try:
                    proc.kill()
                except Exception:
                    pass
        print("[supervisor] listo.")


# ======================================================================
# MAIN
# ======================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0", help="bind del servidor (def: 0.0.0.0)")
    ap.add_argument("--port", default="8000", help="puerto del servidor (def: 8000)")
    ap.add_argument("--tunnel", default=None,
                    help="nombre de named tunnel (usa cloudflared-config.yml). "
                         "Si se omite, se usa Quick Tunnel.")
    ap.add_argument("--no-tunnel", action="store_true",
                    help="no arrancar cloudflared, solo el servidor local.")
    args = ap.parse_args()

    sup = ProcSupervisor()

    # 1. UVICORN
    sup.spawn("uvicorn", [
        sys.executable, "-m", "uvicorn", "server.app:app",
        "--host", args.host, "--port", str(args.port),
    ])

    # 2. CLOUDFLARED (opcional)
    if not args.no_tunnel:
        if not CLOUDFLARED.exists():
            print(f"[supervisor] AVISO: no encuentro {CLOUDFLARED.name} en {ROOT}")
            print("[supervisor] continuando sin tunnel (solo local).")
        else:
            # espera a que uvicorn este levantando antes de arrancar el tunnel
            time.sleep(2)
            if args.tunnel:
                if not CONFIG_YML.exists():
                    print(f"[supervisor] ERROR: falta {CONFIG_YML.name} para named tunnel")
                    sup.stop()
                    return
                cmd = [str(CLOUDFLARED), "tunnel",
                       "--config", str(CONFIG_YML),
                       "run", args.tunnel]
            else:
                cmd = [str(CLOUDFLARED), "tunnel",
                       "--url", f"http://localhost:{args.port}"]
            sup.spawn("cloudflared", cmd)

    if args.no_tunnel:
        print()
        print("=" * 78)
        print(f"  Servidor local: http://localhost:{args.port}")
        print(f"  Panel admin:    http://localhost:{args.port}/admin")
        print("=" * 78)
        print()

    # 3. mantener vivo hasta Ctrl+C
    try:
        while any(p.poll() is None for _, p in sup.procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        sup.stop()


if __name__ == "__main__":
    main()
