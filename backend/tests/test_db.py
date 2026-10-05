"""Schema tests.

Two layers:

* `TestMigrationMatchesModels` needs no database. It renders the DDL implied by
  `app.models` and the DDL the migration actually emits, and fails if they
  disagree — which is what stops the hand-written migration drifting.
* `TestUserRows` exercises a real Postgres and is skipped unless
  `TEST_DATABASE_URL` is set. It creates and drops tables, so it deliberately
  refuses to use `DATABASE_URL`: pointing this at a development database would
  destroy it.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import unittest
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.schema import CreateTable

from app.config import get_settings
from app.db import Base
from app.models import PLAN_FREE, StripeEvent, User

BACKEND = Path(__file__).resolve().parent.parent
PG = sa.dialects.postgresql.dialect()
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def _normalise(ddl: str) -> set[str]:
    """CREATE TABLE body as a set of comparable lines, order-insensitive."""
    body = ddl[ddl.index("(") + 1 : ddl.rindex(")")]
    lines = set()
    depth = 0
    current = ""
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            lines.add(" ".join(current.split()).rstrip(","))
            current = ""
        else:
            current += ch
    if current.strip():
        lines.add(" ".join(current.split()).rstrip(","))
    return {line for line in lines if line}


def _migration_sql() -> str:
    """`alembic upgrade head --sql`, captured in-process. Connects to nothing."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "postgresql+psycopg://u:p@localhost:5432/offline"
    get_settings.cache_clear()
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            command.upgrade(_alembic_config(), "head", sql=True)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
    return buffer.getvalue()


class TestMigrationMatchesModels(unittest.TestCase):
    """The hand-written migration must say exactly what the models say."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = _migration_sql()

    def _migration_table(self, name: str) -> str:
        match = re.search(
            rf"CREATE TABLE {name} \((.*?)\n\);", self.sql, re.S
        )
        self.assertIsNotNone(match, f"migration does not create {name}")
        return f"CREATE TABLE {name} ({match.group(1)}\n)"

    def test_tables_present(self) -> None:
        for name in ("users", "stripe_events"):
            self.assertIn(f"CREATE TABLE {name}", self.sql)

    def test_ddl_matches_models(self) -> None:
        for table in Base.metadata.sorted_tables:
            expected = _normalise(str(CreateTable(table).compile(dialect=PG)))
            actual = _normalise(self._migration_table(table.name))
            self.assertEqual(
                expected,
                actual,
                f"{table.name}: migration and models disagree.\n"
                f"  only in models:    {sorted(expected - actual)}\n"
                f"  only in migration: {sorted(actual - expected)}",
            )

    def test_spec_columns_exact(self) -> None:
        """Column names are fixed by the spec; a rename is a breaking change."""
        self.assertEqual(
            [c.name for c in Base.metadata.tables["users"].columns],
            [
                "id",
                "clerk_user_id",
                "email",
                "plan",
                "subscription_status",
                "stripe_customer_id",
                "stripe_subscription_id",
                "total_generations",
                "day_generations",
                "day_date",
                "created_at",
            ],
        )
        self.assertEqual(
            [c.name for c in Base.metadata.tables["stripe_events"].columns],
            ["id", "received_at"],
        )

    def test_downgrade_is_reversible(self) -> None:
        self.assertIn("DROP TABLE users", _downgrade_sql())
        self.assertIn("DROP TABLE stripe_events", _downgrade_sql())


def _downgrade_sql() -> str:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "postgresql+psycopg://u:p@localhost:5432/offline"
    get_settings.cache_clear()
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            command.downgrade(_alembic_config(), "0001_initial:base", sql=True)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
    return buffer.getvalue()


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL to a throwaway Postgres to run these "
    "(they create and drop tables)",
)
class TestUserRows(unittest.TestCase):
    """Round-trip a user through a real database, applied by the migration."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL  # type: ignore[assignment]
        get_settings.cache_clear()
        cfg = _alembic_config()
        command.downgrade(cfg, "base")  # start from empty, even after a crash
        command.upgrade(cfg, "head")
        cls.engine = sa.create_engine(TEST_DATABASE_URL, future=True)
        cls.Session = sa.orm.sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls) -> None:
        command.downgrade(_alembic_config(), "base")
        cls.engine.dispose()
        if cls._previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls._previous
        get_settings.cache_clear()

    def setUp(self) -> None:
        with self.Session() as s:
            s.query(User).delete()
            s.query(StripeEvent).delete()
            s.commit()

    def test_create_and_read_back(self) -> None:
        with self.Session() as s:
            s.add(User(clerk_user_id="user_abc", email="jane@example.com"))
            s.commit()
        with self.Session() as s:
            user = s.query(User).filter_by(clerk_user_id="user_abc").one()
            self.assertEqual(user.email, "jane@example.com")
            self.assertIsInstance(user.id, uuid.UUID)
            self.assertEqual(user.plan, PLAN_FREE)
            self.assertEqual(user.total_generations, 0)
            self.assertEqual(user.day_generations, 0)
            self.assertIsNone(user.day_date)
            self.assertIsNone(user.stripe_customer_id)
            self.assertIsNotNone(user.created_at)
            self.assertIsNotNone(user.created_at.tzinfo)

    def test_clerk_user_id_is_unique(self) -> None:
        with self.Session() as s:
            s.add(User(clerk_user_id="user_dup", email="a@example.com"))
            s.commit()
        with self.assertRaises(sa.exc.IntegrityError):
            with self.Session() as s:
                s.add(User(clerk_user_id="user_dup", email="b@example.com"))
                s.commit()

    def test_plan_check_constraint(self) -> None:
        with self.assertRaises(sa.exc.IntegrityError):
            with self.Session() as s:
                s.add(
                    User(
                        clerk_user_id="user_badplan",
                        email="c@example.com",
                        plan="tutor",
                    )
                )
                s.commit()

    def test_stripe_event_id_is_primary_key(self) -> None:
        with self.Session() as s:
            s.add(StripeEvent(id="evt_1"))
            s.commit()
        with self.assertRaises(sa.exc.IntegrityError):
            with self.Session() as s:
                s.add(StripeEvent(id="evt_1"))
                s.commit()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
