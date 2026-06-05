from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_trace_db_url() -> str:
    if not settings.trace_db_url:
        raise RuntimeError("TRACE_DB_URL is not configured")
    return settings.trace_db_url


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_trace_db_url(),
            pool_size=settings.trace_db_pool_size,
            max_overflow=settings.trace_db_max_overflow,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            future=True,
        )
    return _session_factory


@contextmanager
def trace_db_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping_trace_db() -> bool:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
