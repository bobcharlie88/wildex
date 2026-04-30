"""
Database configuration.

Engine creation is lazy — if DATABASE_URL is still a placeholder or
PostgreSQL is unreachable the rest of the app starts normally. Endpoints
that write to the DB handle the unavailable state gracefully and return
saved=False rather than crashing.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

_URL = os.getenv("DATABASE_URL", "")
_PLACEHOLDER = "postgresql://user:password@localhost/wildex"


class Base(DeclarativeBase):
    pass


def _make_engine():
    if not _URL or _URL == _PLACEHOLDER:
        return None
    return create_engine(_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)


engine = _make_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) if engine else None


def get_db():
    """FastAPI dependency. Raises RuntimeError if DB not configured."""
    if SessionLocal is None:
        raise RuntimeError("Database not configured — update DATABASE_URL in .env")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def db_available() -> bool:
    """True if the database is reachable right now."""
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def create_tables() -> None:
    """Create all tables. Call once at startup after models are imported."""
    if engine is None:
        raise RuntimeError("DATABASE_URL not configured")
    Base.metadata.create_all(bind=engine)
