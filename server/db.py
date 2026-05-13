"""SQLite engine + Base + session factory."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("SERVER_DB_PATH", DATA_DIR / "server.db"))
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations() -> None:
    """Pequenas migraciones idempotentes para BDs antiguas (SQLite)."""
    with engine.begin() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(users)")]
        if cols and "is_admin" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"
            )
        if cols and "pinned_ua_hash" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN pinned_ua_hash VARCHAR(64)")
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN pinned_ip VARCHAR(64)")
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN pinned_at DATETIME")
        if cols and "pinned_stable_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN pinned_stable_id VARCHAR(64)")
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN pinned_hostname VARCHAR(120)")
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN pinned_machine_guid VARCHAR(64)")

        # access_log: columnas nuevas de device fingerprint
        ac = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(access_log)")]
        if ac and "stable_id" not in ac:
            conn.exec_driver_sql("ALTER TABLE access_log ADD COLUMN stable_id VARCHAR(64)")
            conn.exec_driver_sql("ALTER TABLE access_log ADD COLUMN hostname VARCHAR(120)")
            conn.exec_driver_sql("ALTER TABLE access_log ADD COLUMN machine_guid VARCHAR(64)")
            conn.exec_driver_sql("ALTER TABLE access_log ADD COLUMN device_info TEXT")
