"""CLI de administracion: crea/lista/desactiva usuarios y emite keys.

Uso:
  py -m server.admin create-user <nombre>
  py -m server.admin list
  py -m server.admin disable <id|nombre>
  py -m server.admin enable <id|nombre>
  py -m server.admin rotate-key <id|nombre>
"""
from __future__ import annotations

import sys

import click
from sqlalchemy.orm import Session

from .auth import generate_api_key, hash_key
from .db import Base, SessionLocal, engine, run_migrations
from .models import User


def _ensure_tables():
    Base.metadata.create_all(engine)
    run_migrations()


def _find(db: Session, ident: str) -> User | None:
    if ident.isdigit():
        return db.get(User, int(ident))
    return db.query(User).filter(User.name == ident).first()


@click.group()
def cli():
    """Gestion de usuarios del servidor."""
    _ensure_tables()


@cli.command("create-user")
@click.argument("name")
def create_user(name: str):
    """Crea usuario nuevo y devuelve su API key (no se guarda en claro)."""
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.name == name).first()
        if existing:
            click.echo(f"ERROR: ya existe usuario '{name}' (id={existing.id})")
            sys.exit(1)

        key = generate_api_key()
        user = User(name=name, api_key_hash=hash_key(key))
        db.add(user)
        db.commit()
        db.refresh(user)

        click.echo("")
        click.echo("=" * 60)
        click.echo(f"  Usuario creado: {name}  (id={user.id})")
        click.echo("=" * 60)
        click.echo(f"  API KEY: {key}")
        click.echo("=" * 60)
        click.echo("  GUARDA ESTA KEY. No se puede recuperar despues.")
        click.echo("  Comparte por canal seguro (Signal, DM privado, etc.).")
        click.echo("")
    finally:
        db.close()


@cli.command("list")
def list_users():
    """Lista usuarios y su actividad."""
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id).all()
        if not users:
            click.echo("  (sin usuarios)")
            return

        click.echo(f"  {'ID':<4} {'Nombre':<20} {'Estado':<10} {'Orders':>10} {'History':>10} {'Ultimo visto':<25}")
        click.echo("  " + "-" * 80)
        for u in users:
            estado = "DISABLED" if u.disabled else "activo"
            last = u.last_seen_at.strftime("%Y-%m-%d %H:%M:%S") if u.last_seen_at else "-"
            click.echo(f"  {u.id:<4} {u.name:<20} {estado:<10} {u.orders_uploaded:>10} {u.history_uploaded:>10} {last:<25}")
    finally:
        db.close()


@cli.command("disable")
@click.argument("ident")
def disable(ident: str):
    """Desactiva usuario (su key deja de funcionar)."""
    db = SessionLocal()
    try:
        u = _find(db, ident)
        if not u:
            click.echo(f"ERROR: usuario '{ident}' no encontrado")
            sys.exit(1)
        u.disabled = True
        db.commit()
        click.echo(f"  Usuario {u.name} (id={u.id}) DESACTIVADO")
    finally:
        db.close()


@cli.command("enable")
@click.argument("ident")
def enable(ident: str):
    """Reactiva usuario."""
    db = SessionLocal()
    try:
        u = _find(db, ident)
        if not u:
            click.echo(f"ERROR: usuario '{ident}' no encontrado")
            sys.exit(1)
        u.disabled = False
        db.commit()
        click.echo(f"  Usuario {u.name} (id={u.id}) ACTIVADO")
    finally:
        db.close()


@cli.command("rotate-key")
@click.argument("ident")
def rotate_key(ident: str):
    """Genera una nueva key (invalida la anterior)."""
    db = SessionLocal()
    try:
        u = _find(db, ident)
        if not u:
            click.echo(f"ERROR: usuario '{ident}' no encontrado")
            sys.exit(1)
        key = generate_api_key()
        u.api_key_hash = hash_key(key)
        db.commit()
        click.echo("")
        click.echo(f"  Nueva API KEY para {u.name}: {key}")
        click.echo("")
    finally:
        db.close()


@cli.command("make-admin")
@click.argument("ident")
def make_admin(ident: str):
    """Da permisos de administrador al usuario (acceso al panel /admin)."""
    db = SessionLocal()
    try:
        u = _find(db, ident)
        if not u:
            click.echo(f"ERROR: usuario '{ident}' no encontrado")
            sys.exit(1)
        u.is_admin = True
        db.commit()
        click.echo(f"  {u.name} (id={u.id}) ahora es ADMIN")
    finally:
        db.close()


@cli.command("revoke-admin")
@click.argument("ident")
def revoke_admin(ident: str):
    """Revoca permisos de administrador."""
    db = SessionLocal()
    try:
        u = _find(db, ident)
        if not u:
            click.echo(f"ERROR: usuario '{ident}' no encontrado")
            sys.exit(1)
        u.is_admin = False
        db.commit()
        click.echo(f"  {u.name} (id={u.id}) ya no es admin")
    finally:
        db.close()


if __name__ == "__main__":
    cli()
