from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from albion_capture.core.config import DatabaseConfig


class Base(DeclarativeBase):
    pass


def create_db_engine(config: DatabaseConfig):
    return create_engine(
        config.url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )


def create_session_factory(config: DatabaseConfig) -> sessionmaker[Session]:
    engine = create_db_engine(config)
    return sessionmaker(bind=engine)
