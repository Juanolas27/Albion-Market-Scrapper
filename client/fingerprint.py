"""Fingerprint del dispositivo desde el cliente (solo stdlib).

Se envia al servidor en el header X-Device-Info como base64(JSON).
Usado por el launcher y por el sniffer para que el admin pueda identificar
desde que PC concreto esta subiendo datos una API key.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import platform
import socket
import subprocess
import uuid


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _windows_machine_guid() -> str | None:
    """GUID estable de la instalacion de Windows (unico por PC)."""
    try:
        import winreg
        k = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
        v, _ = winreg.QueryValueEx(k, "MachineGuid")
        winreg.CloseKey(k)
        return v
    except Exception:
        return None


def _wmic(query: str) -> str | None:
    """Pequeno helper para leer WMIC (Windows). Silencioso si falla."""
    try:
        out = subprocess.check_output(
            ["wmic", *query.split()],
            stderr=subprocess.DEVNULL, timeout=5,
            creationflags=0x08000000 if os.name == "nt" else 0,  # NO_WINDOW
        )
        text = out.decode("utf-8", "replace").strip().splitlines()
        # formato: "Header\r\nvalue"
        return text[-1].strip() if len(text) >= 2 else None
    except Exception:
        return None


def _all_macs() -> list[str]:
    """Todas las MACs de las interfaces (via uuid.getnode + fallback)."""
    macs = set()
    mac = "%012x" % uuid.getnode()
    if mac != "000000000000":
        macs.add(":".join(mac[i:i+2] for i in range(0, 12, 2)))
    try:
        out = subprocess.check_output(
            ["ipconfig", "/all"] if os.name == "nt" else ["ip", "link"],
            stderr=subprocess.DEVNULL, timeout=3,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        text = out.decode("utf-8", "replace")
        import re
        for m in re.findall(r"([0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})", text):
            macs.add(m.replace("-", ":").lower())
    except Exception:
        pass
    return sorted(macs)


def collect() -> dict:
    """Devuelve dict con fingerprint estable del dispositivo."""
    info = {
        "hostname": _safe(socket.gethostname, "-"),
        "fqdn": _safe(socket.getfqdn, "-"),
        "os": _safe(platform.platform, "-"),
        "os_system": _safe(platform.system, "-"),
        "os_release": _safe(platform.release, "-"),
        "os_version": _safe(platform.version, "-"),
        "machine": _safe(platform.machine, "-"),
        "processor": _safe(platform.processor, "-"),
        "cpu_count": os.cpu_count(),
        "python": _safe(platform.python_version, "-"),
        "user": _safe(getpass.getuser, "-"),
        "macs": _all_macs(),
        "machine_guid": _windows_machine_guid(),
    }

    if os.name == "nt":
        # Extras WMIC (a veces desaparecen en Win11 pero intentamos)
        info["bios_serial"] = _wmic("bios get serialnumber")
        info["board_serial"] = _wmic("baseboard get serialnumber")
        info["system_uuid"] = _wmic("csproduct get uuid")
        info["disk_serial"] = _wmic("diskdrive get serialnumber")

    # ID estable: mezcla de los campos mas unicos y dificiles de falsear.
    stable_parts = [
        info.get("machine_guid") or "",
        info.get("system_uuid") or "",
        info.get("bios_serial") or "",
        info.get("board_serial") or "",
        info.get("hostname") or "",
        ",".join(info.get("macs") or []),
    ]
    stable_raw = "|".join(p for p in stable_parts if p)
    info["stable_id"] = hashlib.sha256(stable_raw.encode("utf-8")).hexdigest()[:32]
    return info


def encode_header(info: dict | None = None) -> str:
    """Codifica el fingerprint en base64(JSON) apto para un header HTTP."""
    if info is None:
        info = collect()
    raw = json.dumps(info, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


if __name__ == "__main__":
    import pprint
    pprint.pp(collect())
