from collections.abc import Generator
from time import monotonic

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
database_url = settings.database_url
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    connect_args = {"connect_timeout": settings.database_connect_timeout_seconds}

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    pool_timeout=settings.database_pool_timeout_seconds,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def database_status() -> dict:
    """Return a bounded, non-secret database status for health endpoints."""
    started = monotonic()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return {
            "status": "unavailable",
            "latency_ms": round((monotonic() - started) * 1000),
        }
    return {
        "status": "ok",
        "latency_ms": round((monotonic() - started) * 1000),
    }


def create_schema() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
