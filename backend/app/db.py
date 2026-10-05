"""Database engine, session factory and declarative base.

The engine is built lazily from `DATABASE_URL` so that importing this module —
which Alembic and the tests both do — never requires a reachable database.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

# Deterministic constraint names. Without these, Postgres invents names like
# `users_email_key`, autogenerate reports phantom diffs, and an unnamed CHECK
# cannot be dropped in a later migration.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base. Alembic autogenerates against `Base.metadata`."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def database_url() -> str:
    """The configured URL, or a pointed error naming what to set."""
    url = get_settings().database_url
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy backend/.env.example to backend/.env "
            "and point DATABASE_URL at a Postgres database."
        )
    return url


@lru_cache
def get_engine() -> Engine:
    """Process-wide engine. `pool_pre_ping` survives a dropped connection."""
    return create_engine(database_url(), pool_pre_ping=True, future=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed on the way out."""
    with get_session_factory()() as session:
        yield session
