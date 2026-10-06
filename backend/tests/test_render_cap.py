"""The render cap: 50 PDFs a day, a bounded request body, a bounded render.

`/api/render-pdf` reserves no generation slot, because re-downloading a paper
you already own has to stay free. That left the most expensive endpoint we have
— one headless Chromium per call, printing HTML and CSS that arrived over the
wire — as the only one with no ceiling at all. Three limits close that, and
each is tested where it actually has to hold:

* `TestRenderCounter` calls the `count_render` dependency directly, so reaching
  the fifty-first render of a day costs no browser launches.
* `TestRenderCapOverHttp` pins the status codes and bodies the frontend keys
  off, and that a day of downloading cannot block generating.
* `TestBodyLimit` proves the size guard runs *before* the body is parsed — with
  a body that would fail validation if it ever got that far, so a 413 instead
  of a 422 is the only way to know.
* `TestRenderTimeout` wedges the renderer and checks the request comes back
  inside its budget with no Chromium left running.

Needs `TEST_DATABASE_URL` (these create and drop tables, so they refuse to
touch `DATABASE_URL`) and a Chromium installed for Playwright.
"""

from __future__ import annotations

import os
import subprocess
import time
import unittest
from datetime import date, timedelta

import sqlalchemy as sa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import auth, limits, main
from app.config import get_settings
from app.db import Base, get_db
from app.limits import count_render
from app.main import app
from app.models import PLAN_FREE, PLAN_MONTHLY, User
from app.render_guard import MAX_RENDER_BODY_BYTES
from tests.fake_clerk import PUBLIC_KEY, auth_header, make_token

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

#: A fixed Europe/London day, so a run at 23:59:59 cannot straddle midnight.
TODAY = date(2026, 10, 5)
TOMORROW = TODAY + timedelta(days=1)

#: The cap under test. Matches `MAX_DAILY_RENDERS` in the spec.
CAP = 50

#: A document that renders in well under a second.
SMALL_BODY = {"html": "<p>x</p>", "css": "", "filename": "paper.pdf"}

#: A script that never returns, so the renderer wedges and `page.pdf()` — which
#: takes no timeout of its own — is never reached. What the budget is for.
WEDGE_HTML = "<p>wedge</p><script>while (true) {}</script>"

#: Seconds to allow a killed render's processes to finish dying before counting
#: survivors. A successful render's Chromium is still exiting as the call
#: returns, so a bare count straight afterwards reads one too many.
SETTLE_SECONDS = 6


def chromium_processes() -> list[str]:
    """Every live Playwright-managed browser process on this machine.

    Matched on the browsers directory Playwright installs into, which appears
    in the command line of Chromium and all of its helpers.
    """
    listing = subprocess.run(
        ["ps", "-A", "-o", "command="], capture_output=True, text=True
    ).stdout
    return [line for line in listing.splitlines() if "ms-playwright" in line]


def await_no_new_chromium(baseline: int) -> int:
    """Wait for the browser count to fall back to `baseline`, then report it."""
    deadline = time.monotonic() + SETTLE_SECONDS
    while time.monotonic() < deadline:
        count = len(chromium_processes())
        if count <= baseline:
            return count
        time.sleep(0.25)
    return len(chromium_processes())


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL to a throwaway Postgres to run these "
    "(they create and drop tables)",
)
class RenderCapTestCase(unittest.TestCase):
    """A test database, a client authenticated as Clerk, and a frozen clock."""

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
        cls.client = TestClient(app)
        #: For the "the render blew up" test: hand back the 500 rather than
        #: re-raising it into the test.
        cls.failing_client = TestClient(app, raise_server_exceptions=False)

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
        self.today = TODAY
        limits.london_today = lambda: self.today
        os.environ["FREE_GENERATION_LIMIT"] = "1"
        os.environ["DAILY_GENERATION_LIMIT"] = "10"
        os.environ["MAX_DAILY_ATTEMPTS"] = "20"
        os.environ["MAX_DAILY_RENDERS"] = str(CAP)
        os.environ["AUTHORIZED_PARTIES"] = "http://localhost:5173"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        auth.signing_key = self._real_signing_key
        limits.london_today = self._real_today
        os.environ.pop("RENDER_TIMEOUT_SECONDS", None)
        get_settings.cache_clear()

    # --- fixtures -----------------------------------------------------------

    def given_user(
        self,
        *,
        clerk_user_id: str = "user_render",
        email: str = "render@example.com",
        plan: str = PLAN_FREE,
        day_renders: int = 0,
        render_date: date | None = None,
    ) -> User:
        with self.Session() as s:
            user = User(
                clerk_user_id=clerk_user_id,
                email=email,
                plan=plan,
                day_renders=day_renders,
                render_date=render_date,
            )
            s.add(user)
            s.commit()
            return user

    def at_the_cap(self, **kwargs) -> User:
        """A user who has already rendered the day's full allowance."""
        return self.given_user(day_renders=CAP, render_date=TODAY, **kwargs)

    def renders(self, user: User) -> tuple[int, date | None]:
        with self.Session() as s:
            fresh = (
                s.query(User).filter_by(clerk_user_id=user.clerk_user_id).one()
            )
            return fresh.day_renders, fresh.render_date

    def spend_render(self, user: User) -> int:
        """Spend one render, the way FastAPI would, minus FastAPI.

        Returns the day's count. The `RenderCount` the dependency hands back
        also carries a refund, which only the concurrency gate uses — see
        `test_render_concurrency.py`.
        """
        with self.Session() as session:
            attached = (
                session.query(User)
                .filter_by(clerk_user_id=user.clerk_user_id)
                .one()
            )
            return count_render(user=attached, db=session).day_renders

    def token_for(self, user: User) -> str:
        return make_token(sub=user.clerk_user_id, email=user.email)

    def post_render(self, user: User, body=None, client: TestClient | None = None):
        return (client or self.client).post(
            "/api/render-pdf",
            json=SMALL_BODY if body is None else body,
            headers=auth_header(self.token_for(user)),
        )

    def assert_too_many(self, user: User) -> None:
        with self.assertRaises(HTTPException) as caught:
            self.spend_render(user)
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.detail, {"code": "too_many_renders"})


class TestRenderCounter(RenderCapTestCase):
    """The counter itself: one per render, never refunded, daily reset."""

    def test_each_render_spends_one(self) -> None:
        user = self.given_user()
        for n in range(1, 4):
            self.assertEqual(self.spend_render(user), n)
        self.assertEqual(self.renders(user), (3, TODAY))

    def test_the_fifty_first_render_of_a_day_is_refused(self) -> None:
        """The done-when, reached without fifty browser launches."""
        user = self.at_the_cap()
        self.assert_too_many(user)

    def test_a_refused_render_writes_nothing(self) -> None:
        """A looping client must not keep topping its own counter up."""
        user = self.at_the_cap()
        for _ in range(3):
            self.assert_too_many(user)
        self.assertEqual(self.renders(user), (CAP, TODAY))

    def test_the_cap_applies_to_a_monthly_plan_too(self) -> None:
        """An abuse ceiling, not an allowance — paying does not lift it."""
        user = self.at_the_cap(
            clerk_user_id="user_render_monthly",
            email="rm@example.com",
            plan=PLAN_MONTHLY,
        )
        self.assert_too_many(user)

    def test_the_counter_resets_the_next_london_day(self) -> None:
        user = self.at_the_cap()
        self.assert_too_many(user)
        self.today = TOMORROW
        self.assertEqual(self.spend_render(user), 1)
        self.assertEqual(self.renders(user), (1, TOMORROW))

    def test_yesterdays_count_does_not_carry_over(self) -> None:
        """A stale `render_date` is rebased, not added to."""
        user = self.given_user(day_renders=40, render_date=TODAY - timedelta(days=1))
        self.assertEqual(self.spend_render(user), 1)
        self.assertEqual(self.renders(user), (1, TODAY))

    def test_the_cap_follows_the_environment(self) -> None:
        os.environ["MAX_DAILY_RENDERS"] = "2"
        get_settings.cache_clear()
        user = self.given_user()
        self.spend_render(user)
        self.spend_render(user)
        self.assert_too_many(user)
        self.assertEqual(self.renders(user), (2, TODAY))


class TestRenderCapOverHttp(RenderCapTestCase):
    """What the endpoint answers, and what it still lets through."""

    def test_a_render_under_the_cap_works_and_counts(self) -> None:
        user = self.given_user()
        response = self.post_render(user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertEqual(self.renders(user), (1, TODAY))

    def test_over_the_cap_is_429_too_many_renders(self) -> None:
        user = self.at_the_cap()
        response = self.post_render(user)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {"detail": {"code": "too_many_renders"}})

    def test_generating_still_works_at_the_render_cap(self) -> None:
        """The two ceilings are separate counters, so one cannot block the other.

        A day of re-downloading must not cost someone the paper they are
        entitled to make.
        """
        user = self.at_the_cap()
        self.assertEqual(self.post_render(user).status_code, 429)
        generated = self.client.post(
            "/api/generate-paper",
            json={
                "topics": ["percentages"],
                "target_marks": 20,
                "include_answers": True,
                "seed": 11,
            },
            headers=auth_header(self.token_for(user)),
        )
        self.assertEqual(generated.status_code, 200)

    def test_an_unauthenticated_render_counts_nothing(self) -> None:
        response = self.client.post("/api/render-pdf", json=SMALL_BODY)
        self.assertEqual(response.status_code, 401)
        with self.Session() as s:
            self.assertEqual(s.query(User).count(), 0)

    def test_a_failed_render_is_not_refunded(self) -> None:
        """The Chromium launch is the cost, whether or not a PDF comes out."""
        user = self.given_user()

        def explode(*args, **kwargs):
            raise RuntimeError("chromium fell over")

        real = main.render_pdf
        main.render_pdf = explode
        try:
            response = self.post_render(user, client=self.failing_client)
        finally:
            main.render_pdf = real

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            self.renders(user), (1, TODAY), "a failed render must still count"
        )


class TestBodyLimit(RenderCapTestCase):
    """The size guard, and the proof that it runs before the body is parsed."""

    #: Comfortably over the 2 MB ceiling.
    OVERSIZE = MAX_RENDER_BODY_BYTES + 1024

    def oversized_json(self) -> bytes:
        """A valid, oversized request body."""
        filler = "x" * self.OVERSIZE
        return b'{"html": "<p>' + filler.encode() + b'</p>", "css": ""}'

    def unparseable_oversized(self) -> bytes:
        """Oversized *and* not JSON at all.

        If the body were parsed before being measured this would be a 422. A
        413 is therefore the only answer that proves the guard ran first.
        """
        return b'{"html": "' + (b"x" * self.OVERSIZE) + b'" NOT-JSON'

    def post_raw(self, user: User | None, content: bytes | object, **kwargs):
        headers = {"Content-Type": "application/json"}
        if user is not None:
            headers.update(auth_header(self.token_for(user)))
        return self.client.post(
            "/api/render-pdf", content=content, headers=headers, **kwargs
        )

    def test_an_oversized_body_is_413(self) -> None:
        user = self.given_user()
        response = self.post_raw(user, self.oversized_json())
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {"detail": {"code": "render_too_large"}})

    def test_it_is_refused_before_the_body_is_parsed(self) -> None:
        """The done-when: a 413 where a parse would have produced a 422."""
        user = self.given_user()
        response = self.post_raw(user, self.unparseable_oversized())
        self.assertEqual(
            response.status_code,
            413,
            "a 422 here means the JSON was parsed before being measured",
        )
        self.assertEqual(response.json(), {"detail": {"code": "render_too_large"}})

    def test_an_oversized_body_launches_no_chromium(self) -> None:
        user = self.given_user()
        calls: list[tuple] = []

        def record(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("render started on an oversized body")

        real = main.render_pdf
        main.render_pdf = record
        try:
            response = self.post_raw(user, self.oversized_json())
        finally:
            main.render_pdf = real
        self.assertEqual(response.status_code, 413)
        self.assertEqual(calls, [])

    def test_an_oversized_body_spends_no_render(self) -> None:
        """It is refused ahead of the counter, so it cannot exhaust the day."""
        user = self.given_user()
        self.post_raw(user, self.oversized_json())
        self.assertEqual(self.renders(user), (0, None))

    def test_an_oversized_body_is_refused_without_a_session(self) -> None:
        """Before routing means before auth: no account is even looked up."""
        response = self.post_raw(None, self.oversized_json())
        self.assertEqual(response.status_code, 413)
        with self.Session() as s:
            self.assertEqual(s.query(User).count(), 0)

    def json_of_size(self, total: int) -> bytes:
        """A valid request body of exactly `total` bytes."""
        prefix, suffix = b'{"css": "", "html": "', b'"}'
        return prefix + b"y" * (total - len(prefix) - len(suffix)) + suffix

    def without_rendering(self):
        """Swap the renderer for a stub, so a boundary test costs no Chromium.

        Returns the list the stub records calls in. What is under test here is
        which bodies reach the handler, not what Chromium does with a megabyte
        of unbreakable text — that is the timeout's problem, not the guard's.
        """
        calls: list[int] = []

        def stub(html: str, css: str, **kwargs) -> bytes:
            calls.append(len(html) + len(css))
            return b"%PDF-1.4 stub"

        real = main.render_pdf
        main.render_pdf = stub
        self.addCleanup(lambda: setattr(main, "render_pdf", real))
        return calls

    def test_a_body_exactly_at_the_limit_is_allowed_through(self) -> None:
        """The guard must not be off by one in the direction that breaks users."""
        user = self.given_user()
        reached = self.without_rendering()
        response = self.post_raw(user, self.json_of_size(MAX_RENDER_BODY_BYTES))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(reached), 1, "an in-limit body did not reach the handler")

    def test_one_byte_over_the_limit_is_refused(self) -> None:
        """The companion case, so the comparison cannot be loosened unnoticed."""
        user = self.given_user()
        reached = self.without_rendering()
        response = self.post_raw(user, self.json_of_size(MAX_RENDER_BODY_BYTES + 1))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(reached, [])

    def test_an_oversized_chunked_body_is_413(self) -> None:
        """No `Content-Length` to read, so the bytes are counted as they land."""
        user = self.given_user()
        chunk = b"x" * 65536
        body = self.oversized_json()

        def stream():
            for start in range(0, len(body), len(chunk)):
                yield body[start : start + len(chunk)]

        response = self.post_raw(user, stream())
        self.assertIsNone(
            response.request.headers.get("content-length"),
            "expected a chunked upload — the header path is tested elsewhere",
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {"detail": {"code": "render_too_large"}})

    def test_an_in_limit_chunked_body_is_replayed_intact(self) -> None:
        """Counting a streamed body must not consume it."""
        user = self.given_user()
        body = b'{"html": "<p>chunked</p>", "css": ""}'

        def stream():
            yield body[:10]
            yield body[10:]

        response = self.post_raw(user, stream())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")


class TestRenderTimeout(RenderCapTestCase):
    """A document that wedges the renderer must not pin a worker."""

    #: Short enough to keep the suite quick, long enough that a healthy render
    #: finishes well inside it.
    BUDGET = 8

    def setUp(self) -> None:
        super().setUp()
        os.environ["RENDER_TIMEOUT_SECONDS"] = str(self.BUDGET)
        get_settings.cache_clear()

    def test_a_wedged_render_is_504_inside_its_budget(self) -> None:
        user = self.given_user()
        baseline = len(chromium_processes())

        started = time.monotonic()
        response = self.post_render(
            user, body={"html": WEDGE_HTML, "css": "", "filename": "paper.pdf"}
        )
        elapsed = time.monotonic() - started

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json(), {"detail": {"code": "render_timeout"}})
        self.assertLess(
            elapsed,
            self.BUDGET * 3,
            f"the 504 took {elapsed:.1f}s — the budget is not being enforced",
        )
        self.assertLessEqual(
            await_no_new_chromium(baseline),
            baseline,
            "a killed render left Chromium running",
        )

    def test_a_timed_out_render_still_counts(self) -> None:
        """It launched a browser and burned the full budget; that is the cost."""
        user = self.given_user()
        self.post_render(
            user, body={"html": WEDGE_HTML, "css": "", "filename": "paper.pdf"}
        )
        self.assertEqual(self.renders(user), (1, TODAY))

    def test_a_healthy_render_is_unaffected_by_the_budget(self) -> None:
        user = self.given_user()
        self.assertEqual(self.post_render(user).status_code, 200)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
