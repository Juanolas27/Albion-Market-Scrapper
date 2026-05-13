from __future__ import annotations

import yaml
from pathlib import Path
from pydantic import BaseModel


class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str = "albion_market"
    user: str = "postgres"
    password: str = "postgres"

    @property
    def url(self) -> str:
        return f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class CaptureConfig(BaseModel):
    game_port: int = 5056
    batch_size: int = 100
    flush_interval_seconds: int = 5
    heartbeat_interval_seconds: int = 30


class WorkerConfig(BaseModel):
    city: str
    city_id: int
    local_port: int | None = None
    local_ports: list[int] = []


class AppConfig(BaseModel):
    database: DatabaseConfig = DatabaseConfig()
    capture: CaptureConfig = CaptureConfig()
    workers: list[WorkerConfig] = []


def load_config(path: str | Path | None = None) -> AppConfig:
    if path is None:
        path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return AppConfig(**raw)
