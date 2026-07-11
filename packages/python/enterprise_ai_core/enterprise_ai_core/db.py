from collections.abc import Generator
from time import sleep

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base


def _normalize_postgres_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+psycopg://"):
        return dsn
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql+psycopg://", 1)
    return dsn


settings = get_settings()
engine = create_engine(_normalize_postgres_dsn(settings.postgres_dsn), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    attempts = max(1, settings.postgres_connect_retries)
    delay_seconds = max(1, settings.postgres_connect_retry_delay_seconds)
    last_error: OperationalError | None = None

    for attempt in range(1, attempts + 1):
        try:
            with engine.begin() as connection:
                try:
                    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                except Exception:
                    pass
            Base.metadata.create_all(bind=engine)
            return
        except OperationalError as exc:
            last_error = exc
            if attempt == attempts:
                break
            sleep(delay_seconds)

    if last_error is not None:
        raise last_error


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
