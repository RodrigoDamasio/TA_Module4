"""Database engine and sessions."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


def create_db_engine() -> Engine:
    """Create the SQLAlchemy engine from DATABASE_URL.

    SQLite needs `check_same_thread=False` because FastAPI serves requests from a thread
    pool; other databases get a connection pool sized by DB_POOL_SIZE.
    """
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        return create_engine(settings.database_url, connect_args={"check_same_thread": False})
    return create_engine(
        settings.database_url, pool_size=settings.db_pool_size, pool_pre_ping=True
    )


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
