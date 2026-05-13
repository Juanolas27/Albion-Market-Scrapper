"""API key auth: generate, hash, validate + device/IP tracking."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .db import get_db
from .models import AccessLog, User


# ======================================================================
# KEYS
# ======================================================================

def generate_api_key() -> str:
    """Crea una API key nueva: 40 chars alfanumericos."""
    return "alb_" + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    """SHA-256 hex."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ======================================================================
# DEVICE / IP TRACKING
# ======================================================================

def ua_hash(ua: str) -> str:
    return hashlib.sha256(ua.encode("utf-8", "replace")).hexdigest()[:32]


def get_client_ip(request: Request) -> str:
    """IP real respetando proxies (Cloudflare)."""
    for h in ("CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP"):
        v = request.headers.get(h)
        if v:
            return v.split(",")[0].strip()[:64]
    if request.client:
        return request.client.host[:64]
    return "-"


def parse_device_info(request: Request) -> dict:
    """Decodifica el header X-Device-Info (base64(JSON)) si existe."""
    raw = request.headers.get("X-Device-Info")
    if not raw:
        return {}
    try:
        data = json.loads(base64.b64decode(raw).decode("utf-8", "replace"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def record_access(db: Session, user: User, request: Request) -> bool:
    """Registra un acceso. Devuelve True si el device coincide con el pinned.

    Criterio de match (por orden de preferencia):
      1. stable_id del header X-Device-Info (MAC+machine_guid+etc).
      2. ua_hash (User-Agent hash) si no hay fingerprint.
    """
    ua = (request.headers.get("User-Agent") or "-")[:500]
    ip = get_client_ip(request)
    uh = ua_hash(ua)
    path = request.url.path[:200]
    dev = parse_device_info(request)

    stable_id = (dev.get("stable_id") or "")[:64] or None
    hostname = (dev.get("hostname") or "")[:120] or None
    machine_guid = (dev.get("machine_guid") or "")[:64] or None
    # Guardamos el JSON entero (truncado por seguridad)
    dev_json = json.dumps(dev, separators=(",", ":"))[:8000] if dev else None

    match = True
    now = datetime.now(timezone.utc)

    # Primer acceso -> pinear todo
    if not user.pinned_ua_hash and not user.pinned_stable_id:
        user.pinned_ua_hash = uh
        user.pinned_ip = ip
        user.pinned_at = now
        user.pinned_stable_id = stable_id
        user.pinned_hostname = hostname
        user.pinned_machine_guid = machine_guid
    else:
        # Compara por stable_id si tenemos uno pineado
        if user.pinned_stable_id:
            if stable_id and stable_id != user.pinned_stable_id:
                match = False
            elif not stable_id and user.pinned_ua_hash and user.pinned_ua_hash != uh:
                # cliente sin fingerprint (ej. curl) -> fallback a UA
                match = False
        else:
            # no hay pinned_stable_id (cuenta vieja) -> solo UA
            if user.pinned_ua_hash and user.pinned_ua_hash != uh:
                match = False
            # Si ahora recibimos un stable_id, pineamos tambien eso
            if stable_id:
                user.pinned_stable_id = stable_id
                user.pinned_hostname = hostname
                user.pinned_machine_guid = machine_guid

    log = AccessLog(
        user_id=user.id, ip=ip, user_agent=ua, ua_hash=uh,
        device_match=match, path=path,
        stable_id=stable_id, hostname=hostname,
        machine_guid=machine_guid, device_info=dev_json,
    )
    db.add(log)
    return match


# ======================================================================
# VALIDACION DE KEY (comun)
# ======================================================================

def _load_user_or_401(db: Session, key: str) -> User:
    user = db.query(User).filter(User.api_key_hash == hash_key(key)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User disabled")
    return user


# ======================================================================
# DEPENDENCIES
# ======================================================================

def require_user(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> User:
    """Autentica por header (sniffer y admin API)."""
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )
    user = _load_user_or_401(db, x_api_key)
    user.last_seen_at = datetime.now(timezone.utc)
    record_access(db, user, request)
    db.commit()
    return user


def require_session(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Autentica por cookie (viewer web)."""
    key = request.cookies.get("alb_session")
    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No session")
    user = _load_user_or_401(db, key)
    user.last_seen_at = datetime.now(timezone.utc)
    record_access(db, user, request)
    db.commit()
    return user


def require_any_auth(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> User:
    """Acepta tanto header como cookie. Para endpoints consumidos por
    sniffer (header) Y por el viewer web (cookie)."""
    key = x_api_key or request.cookies.get("alb_session")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing credentials",
        )
    user = _load_user_or_401(db, key)
    user.last_seen_at = datetime.now(timezone.utc)
    record_access(db, user, request)
    db.commit()
    return user


def require_admin(user: User = Depends(require_any_auth)) -> User:
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user
