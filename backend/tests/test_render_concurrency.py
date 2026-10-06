"""How many renders may run at once: one per account, a handful per box.

The daily cap bounds a user's renders per day, not per instant. Fifty requests
fired together sit inside every limit the spec had before this one, and the
threadpool would start dozens of Chromiums at once — a few hundred megabytes
each, which on a small box is an out-of-memory kill rather than a slow queue.

These tests drive the ASGI app through `httpx.AsyncClient` and
`asyncio.gather`, not `TestClient`, for one reason: `TestClient` runs each
request in its own event loop, and a limit built out of an `asyncio.Semaphore`
only means anything to tasks sharing a loop. Gathering coroutines is also how
the concurrency under test is made deterministic — both requests are in flight
before either can finish.

The renderer itself is stubbed almost everywhere here. What is under test is
which requests are allowed to run together, not what Chromium does with the
ones that are; `test_render_cap.py` covers the real thing.

Needs `TEST_DATABASE_URL` (these create and drop tables, so they refuse to
touch `DATABASE_URL`).
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import unittest
from datetime import date

import httpx
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app import auth, limits, main, render_slots
from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import PLAN_FREE, User
from tests.fake_clerk import PUBLIC_KEY, auth_header, make_token

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

#: A fixed Europe/London day, so a run at 23:59:59 cannot straddle midnight.
TODAY = date(2026, 10, 5)

BODY = {"html": "<p>x</p>", "css": "", "filename": "paper.pdf"}

#: Long enough that every request in a gather is demonstrably in flight at
#: once, short enough to keep the suite quick.
SLOW_RENDER_SECONDS = 0.5

#: What the stub hands back in place of a PDF. Never parsed here.
STUB_PDF = b"%PDF-1.4 stub"


class RenderTracker:
    """A stand-in renderer that records how many ran at the same time.

    Peak concurrency is the claim these tests actually make, so it is measured
    rather than inferred from wall-clock timings. Called from the threadpool,
    hence the lock.
    """

    def __init__(self, seconds: float = SLOW_RENDER_SECONDS) -> None:
        self.seconds = seconds
        self.started = 0
        self.live = 0
        self.peak = 0
        self._lock = threading.Lock()

    def __call__(self, html: str, css: str, **kwargs: object) -> bytes:
        with self._lock:
            self.started += 1
            self.live += 1
            self.peak = max(self.peak, self.live)
        try:
            time.sleep(self.seconds)
            return STUB_PDF
        finally:
            with self._lock:
                self.live -= 1


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL to a throwaway Postgres to run these "
    "(they create and drop tables)",
)
class RenderConcurrencyTestCase(unittest.TestCase):
    """A test database, a frozen clock, and no concurrency state carried over."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = sa.create_engine(TEST_DATABASE_URL, future=True)
        Base.metadata.drop_all(cls.engine)
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)

        def override_get_db():
            with cls.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()

    def setUp(self) -> None:
        with self.Session() as s:
            s.query(User).delete()
            s.commit()
        self._real_signing_key = auth.signing_key
        auth.signing_key = lambda token: PUBLIC_KEY
        self._real_today = limits.london_today
        limits.london_today = lambda: TODAY
        self._real_render = main.render_pdf
        os.environ["FREE_GENERATION_LIMIT"] = "1"
        os.environ["DAILY_GENERATION_LIMIT"] = "10"
        os.environ["MAX_DAILY_RENDERS"] = "50"
        os.environ["AUTHORIZED_PARTIES"] = "http://localhost:5173"
        get_settings.cache_clear()
        # Every case gets its own loop, and a semaphore belongs to the loop
        # that first waited on it.
        render_slots.reset_render_slots()

    def tearDown(self) -> None:
        auth.signing_key = self._real_signing_key
        limits.london_today = self._real_today
        main.render_pdf = self._real_render
        for name in ("MAX_CONCURRENT_RENDERS", "RENDER_SLOT_WAIT_SECONDS"):
            os.environ.pop(name, None)
        get_settings.cache_clear()
        render_slots.reset_render_slots()

    # --- fixtures -----------------------------------------------------------

    def given_user(self, name: str = "a") -> User:
        """An account with no renders spent today."""
        with self.Session() as s:
            user = User(
                clerk_user_id=f"user_conc_{name}",
                email=f"{name}@example.com",
                plan=PLAN_FREE,
            )
            s.add(user)
            s.commit()
            return user

    def renders(self, user: User) -> int:
        with self.Session() as s:
            return (
                s.query(User)
                .filter_by(clerk_user_id=user.clerk_user_id)
                .one()
                .day_renders
            )

    def configure(self, *, concurrent: int, wait: int | None = None) -> None:
        """Set the two ceilings. `wait` is whole seconds — `_int_env` drops
        anything else and would leave the 10 s default in place."""
        os.environ["MAX_CONCURRENT_RENDERS"] = str(concurrent)
        if wait is not None:
            os.environ["RENDER_SLOT_WAIT_SECONDS"] = str(wait)
        get_settings.cache_clear()
        render_slots.reset_render_slots()

    def tracking_renders(self, seconds: float = SLOW_RENDER_SECONDS) -> RenderTracker:
        """Swap the renderer for one that records its own concurrency."""
        tracker = RenderTracker(seconds)
        main.render_pdf = tracker
        return tracker

    # --- driving the app on one event loop ----------------------------------

    def post_all(self, *users: User, body=None) -> list[httpx.Response]:
        """Fire one render per user, all in flight together, and collect them.

        Ordered to match `users`, whatever order they finished in.
        """

        async def run() -> list[httpx.Response]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await asyncio.gather(
                    *(
                        client.post(
                            "/api/render-pdf",
                            json=BODY if body is None else body,
                            headers=auth_header(
                                make_token(
                                    sub=user.clerk_user_id, email=user.email
                                )
                            ),
                            timeout=60,
                        )
                        for user in users
                    )
                )

        return asyncio.run(run())

    def post_one(self, user: User, body=None) -> httpx.Response:
        return self.post_all(user, body=body)[0]

    def codes(self, responses: list[httpx.Response]) -> list[int]:
        return sorted(r.status_code for r in responses)


class TestOneRenderPerUser(RenderConcurrencyTestCase):
    """An account gets one render at a time. The second is refused, not queued."""

    def test_two_at_once_is_one_200_and_one_429(self) -> None:
        """The done-when, including that the refusal costs nothing."""
        user = self.given_user()
        tracker = self.tracking_renders()

        first, second = self.post_all(user, user)

        self.assertEqual(self.codes([first, second]), [200, 429])
        refused = first if first.status_code == 429 else second
        self.assertEqual(refused.json(), {"detail": {"code": "render_in_progress"}})
        self.assertEqual(
            self.renders(user), 1, "the refused request must spend no render"
        )
        self.assertEqual(tracker.started, 1, "only one render should have run")

    def test_ten_at_once_still_render_only_one(self) -> None:
        """Nothing about the limit depends on there being exactly two."""
        user = self.given_user()
        tracker = self.tracking_renders()

        responses = self.post_all(*([user] * 10))

        self.assertEqual(
            [r.status_code for r in responses].count(200),
            1,
            "exactly one of ten simultaneous renders should succeed",
        )
        self.assertEqual(tracker.started, 1)
        self.assertEqual(self.renders(user), 1)

    def test_the_hold_is_released_after_the_request(self) -> None:
        """Sequential downloads — a paper then its mark scheme — must work."""
        user = self.given_user()
        self.tracking_renders(seconds=0)

        for _ in range(3):
            self.assertEqual(self.post_one(user).status_code, 200)
        self.assertEqual(self.renders(user), 3)

    def test_the_hold_is_released_when_the_render_fails(self) -> None:
        """A 500 must not lock an account out until the process restarts."""
        user = self.given_user()

        def explode(*args: object, **kwargs: object) -> bytes:
            raise RuntimeError("chromium fell over")

        main.render_pdf = explode
        with self.assertRaises(RuntimeError):
            self.post_one(user)

        self.tracking_renders(seconds=0)
        self.assertEqual(self.post_one(user).status_code, 200)

    def test_different_accounts_do_not_block_each_other(self) -> None:
        """The limit is per user; two parents downloading at once is normal."""
        self.configure(concurrent=2)
        first_user, second_user = self.given_user("a"), self.given_user("b")
        tracker = self.tracking_renders()

        responses = self.post_all(first_user, second_user)

        self.assertEqual(self.codes(responses), [200, 200])
        self.assertEqual(tracker.peak, 2, "the two should have run together")


class TestGlobalRenderSlots(RenderConcurrencyTestCase):
    """The box-wide ceiling: a short queue, then 503."""

    def test_a_second_user_waits_and_then_succeeds(self) -> None:
        """The done-when: with one slot, two users serialise rather than fail."""
        self.configure(concurrent=1, wait=30)
        first_user, second_user = self.given_user("a"), self.given_user("b")
        tracker = self.tracking_renders()

        started = time.monotonic()
        responses = self.post_all(first_user, second_user)
        elapsed = time.monotonic() - started

        self.assertEqual(self.codes(responses), [200, 200])
        self.assertEqual(tracker.started, 2)
        self.assertEqual(tracker.peak, 1, "the renders overlapped despite one slot")
        self.assertGreaterEqual(
            elapsed,
            SLOW_RENDER_SECONDS * 2,
            "they finished too fast to have been serialised",
        )

    def test_the_ceiling_is_the_configured_number(self) -> None:
        """Two slots means two at a time, not one and not four."""
        self.configure(concurrent=2, wait=30)
        users = [self.given_user(name) for name in "abcd"]
        tracker = self.tracking_renders()

        responses = self.post_all(*users)

        self.assertEqual(self.codes(responses), [200, 200, 200, 200])
        self.assertEqual(tracker.started, 4)
        self.assertEqual(tracker.peak, 2)

    def test_waiting_past_the_deadline_is_503_render_busy(self) -> None:
        """The done-when: a queue that is not moving is answered, not held."""
        self.configure(concurrent=1, wait=1)
        first_user, second_user = self.given_user("a"), self.given_user("b")
        tracker = self.tracking_renders(seconds=4)

        first, second = self.post_all(first_user, second_user)

        # Whichever got the slot rendered; the other gave up waiting.
        rendered, refused = (
            (first, second) if first.status_code == 200 else (second, first)
        )
        self.assertEqual(rendered.status_code, 200)
        self.assertEqual(refused.status_code, 503)
        self.assertEqual(refused.json(), {"detail": {"code": "render_busy"}})
        self.assertEqual(tracker.started, 1, "the 503 must launch nothing")

    def test_a_503_refunds_the_render_it_counted(self) -> None:
        """Nothing was launched, so the day's allowance must be untouched."""
        self.configure(concurrent=1, wait=1)
        first_user, second_user = self.given_user("a"), self.given_user("b")
        self.tracking_renders(seconds=4)

        first, second = self.post_all(first_user, second_user)

        busy_user = second_user if second.status_code == 503 else first_user
        rendered_user = first_user if busy_user is second_user else second_user
        self.assertEqual(
            self.renders(busy_user), 0, "a 503 must give the render back"
        )
        self.assertEqual(self.renders(rendered_user), 1)

    def test_the_slot_is_released_when_a_render_fails(self) -> None:
        """One crash must not retire a slot for the life of the process."""
        self.configure(concurrent=1, wait=30)
        user = self.given_user()

        def explode(*args: object, **kwargs: object) -> bytes:
            raise RuntimeError("chromium fell over")

        main.render_pdf = explode
        with self.assertRaises(RuntimeError):
            self.post_one(user)

        self.tracking_renders(seconds=0)
        self.assertEqual(self.post_one(user).status_code, 200)

    def test_queueing_is_not_charged_to_the_render_budget(self) -> None:
        """A queued render gets its full budget once it starts, not what is left.

        With one slot and a slow first render, the second waits most of a
        second before starting — and must still be allowed its own 20 s, not
        20 s minus the queue. Checked through the real renderer, since the
        budget lives in the subprocess wrapper the stub replaces.
        """
        self.configure(concurrent=1, wait=30)
        os.environ["RENDER_TIMEOUT_SECONDS"] = "20"
        get_settings.cache_clear()
        self.addCleanup(lambda: os.environ.pop("RENDER_TIMEOUT_SECONDS", None))
        users = [self.given_user("a"), self.given_user("b")]

        responses = self.post_all(*users)

        self.assertEqual(self.codes(responses), [200, 200])
        for response in responses:
            self.assertEqual(response.headers["content-type"], "application/pdf")


class TestOtherEndpointsAreUnaffected(RenderConcurrencyTestCase):
    """The gates belong to the render route and nothing else."""

    def test_generating_is_not_limited_by_a_render_in_flight(self) -> None:
        """A download in progress must not block making a paper."""
        self.configure(concurrent=1, wait=30)
        user = self.given_user()
        self.tracking_renders(seconds=0)
        self.assertEqual(self.post_one(user).status_code, 200)

        async def run() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.post(
                    "/api/generate-paper",
                    json={
                        "topics": ["percentages"],
                        "target_marks": 20,
                        "include_answers": True,
                        "seed": 11,
                    },
                    headers=auth_header(
                        make_token(sub=user.clerk_user_id, email=user.email)
                    ),
                    timeout=60,
                )

        self.assertEqual(asyncio.run(run()).status_code, 200)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
