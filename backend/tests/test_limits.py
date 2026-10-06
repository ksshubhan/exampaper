"""Generation limits: free gets one paper, monthly gets ten a day, no races.

Two layers, both against a real Postgres (the atomicity being tested *is* the
database, so there is nothing to learn from a fake):

* `TestReserve*` calls the `reserve_generation` dependency directly. Fast, and
  it reaches states — the eleventh generation, yesterday's counters — that would
  cost ten paper assemblies each to reach over HTTP.
* `TestGeneratePaper*` drives `POST /api/generate-paper` and pins the status
  codes and bodies the frontend keys off.

`TestAttemptCap` covers the pre-deploy attempt ceiling, which is the one
counter a refund does not touch.

Needs `TEST_DATABASE_URL`: these tests create and drop tables, so they refuse
to touch `DATABASE_URL`.
"""

from __future__ import annotations

import asyncio
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import sqlalchemy as sa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app import auth, limits, main
from app.config import get_settings
from app.db import Base, get_db
from app.limits import Reservation, reserve_generation
from app.main import app
from app.models import PLAN_FREE, PLAN_MONTHLY, User
from app.schema import GeneratePaperRequest
from tests.fake_clerk import PUBLIC_KEY, auth_header, make_token

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

#: A fixed Europe/London day, so a test run at 23:59:59 cannot straddle midnight.
TODAY = date(2026, 10, 5)
TOMORROW = TODAY + timedelta(days=1)

#: Cheap to assemble, and the limit does not care what is in the paper.
PAPER_BODY = {
    "topics": ["percentages"],
    "target_marks": 20,
    "include_answers": True,
    "seed": 11,
}


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL to a throwaway Postgres to run these "
    "(they create and drop tables)",
)
class LimitsTestCase(unittest.TestCase):
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
        #: For the "generation blew up" test: hand back the 500 instead of
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
        os.environ["AUTHORIZED_PARTIES"] = "http://localhost:5173"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        auth.signing_key = self._real_signing_key
        limits.london_today = self._real_today
        get_settings.cache_clear()

    # --- fixtures -----------------------------------------------------------

    def given_user(
        self,
        *,
        clerk_user_id: str = "user_limits",
        email: str = "limits@example.com",
        plan: str = PLAN_FREE,
        total_generations: int = 0,
        day_generations: int = 0,
        day_date: date | None = None,
        day_attempts: int = 0,
        attempt_date: date | None = None,
    ) -> User:
        with self.Session() as s:
            user = User(
                clerk_user_id=clerk_user_id,
                email=email,
                plan=plan,
                total_generations=total_generations,
                day_generations=day_generations,
                day_date=day_date,
                day_attempts=day_attempts,
                attempt_date=attempt_date,
            )
            s.add(user)
            s.commit()
            return user

    def row(self, user: User) -> User:
        with self.Session() as s:
            return s.query(User).filter_by(clerk_user_id=user.clerk_user_id).one()

    def counters(self, user: User) -> tuple[int, int, date | None]:
        fresh = self.row(user)
        return fresh.total_generations, fresh.day_generations, fresh.day_date

    def attempts(self, user: User) -> tuple[int, date | None]:
        fresh = self.row(user)
        return fresh.day_attempts, fresh.attempt_date

    def reserve(self, user: User) -> Reservation:
        """Call the dependency the way FastAPI would, minus FastAPI.

        A fresh session and a fresh `SELECT`, exactly as `get_current_user`
        hands the row over on a real request.
        """
        request = Request({"type": "http", "headers": [], "method": "POST"})
        with self.Session() as session:
            attached = (
                session.query(User)
                .filter_by(clerk_user_id=user.clerk_user_id)
                .one()
            )
            return reserve_generation(request, user=attached, db=session)

    def token_for(self, user: User) -> str:
        return make_token(sub=user.clerk_user_id, email=user.email)

    # --- driving the route without a server ---------------------------------
    #
    # `TestClient` can neither disconnect nor cancel, so the tests that care
    # about an abandoned request call the endpoint coroutine directly with a
    # `receive` channel they control.

    def endpoint(self, reservation: Reservation, receive):
        """The route's coroutine, with a request whose client we control."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/generate-paper",
                "headers": [],
            },
            receive=receive,
        )
        return main.generate_paper(
            GeneratePaperRequest(**PAPER_BODY), request, reservation=reservation
        )

    @staticmethod
    async def still_connected():
        """A client that is there but has nothing more to say."""
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    async def gone():
        """A client that has hung up."""
        return {"type": "http.disconnect"}


class TestReserveFree(LimitsTestCase):
    """Free: one generation, ever."""

    def test_first_reservation_succeeds_and_counts(self) -> None:
        user = self.given_user()
        reservation = self.reserve(user)
        self.assertEqual(reservation.plan, PLAN_FREE)
        self.assertEqual(reservation.total_generations, 1)
        self.assertEqual(self.counters(user), (1, 1, TODAY))

    def test_second_reservation_is_402_upgrade_required(self) -> None:
        user = self.given_user()
        self.reserve(user)
        with self.assertRaises(HTTPException) as caught:
            self.reserve(user)
        self.assertEqual(caught.exception.status_code, 402)
        self.assertEqual(caught.exception.detail, {"code": "upgrade_required"})
        self.assertEqual(self.counters(user), (1, 1, TODAY))

    def test_a_new_day_does_not_restore_the_free_paper(self) -> None:
        """The free allowance is one in total, not one a day."""
        user = self.given_user()
        self.reserve(user)
        self.today = TOMORROW
        with self.assertRaises(HTTPException) as caught:
            self.reserve(user)
        self.assertEqual(caught.exception.status_code, 402)

    def test_free_limit_follows_the_environment(self) -> None:
        os.environ["FREE_GENERATION_LIMIT"] = "3"
        get_settings.cache_clear()
        user = self.given_user()
        for _ in range(3):
            self.reserve(user)
        with self.assertRaises(HTTPException) as caught:
            self.reserve(user)
        self.assertEqual(caught.exception.status_code, 402)
        self.assertEqual(self.counters(user)[0], 3)


class TestReserveMonthly(LimitsTestCase):
    """Monthly: unlimited, behind a fair-use cap of ten a day."""

    def monthly(self, **kwargs) -> User:
        return self.given_user(
            clerk_user_id="user_monthly",
            email="monthly@example.com",
            plan=PLAN_MONTHLY,
            **kwargs,
        )

    def test_ten_succeed_and_the_eleventh_is_429(self) -> None:
        user = self.monthly()
        for n in range(10):
            self.assertEqual(self.reserve(user).day_generations, n + 1)
        with self.assertRaises(HTTPException) as caught:
            self.reserve(user)
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.detail, {"code": "daily_limit_reached"})
        self.assertEqual(self.counters(user), (10, 10, TODAY))

    def test_the_next_day_resets_the_daily_count(self) -> None:
        user = self.monthly(day_generations=10, day_date=TODAY)
        with self.assertRaises(HTTPException):
            self.reserve(user)

        self.today = TOMORROW
        reservation = self.reserve(user)
        self.assertEqual(reservation.day_generations, 1)
        self.assertEqual(self.counters(user), (1, 1, TOMORROW))

    def test_a_stale_day_count_is_rebased_not_added_to(self) -> None:
        """Yesterday's ten do not bleed into today."""
        user = self.monthly(
            total_generations=40, day_generations=10, day_date=TODAY - timedelta(days=1)
        )
        reservation = self.reserve(user)
        self.assertEqual((reservation.total_generations, reservation.day_generations), (41, 1))
        self.assertEqual(self.counters(user), (41, 1, TODAY))

    def test_monthly_is_not_capped_by_the_free_limit(self) -> None:
        user = self.monthly(total_generations=500, day_generations=0, day_date=TODAY)
        self.assertEqual(self.reserve(user).total_generations, 501)

    def test_daily_limit_follows_the_environment(self) -> None:
        os.environ["DAILY_GENERATION_LIMIT"] = "2"
        get_settings.cache_clear()
        user = self.monthly()
        self.reserve(user)
        self.reserve(user)
        with self.assertRaises(HTTPException) as caught:
            self.reserve(user)
        self.assertEqual(caught.exception.status_code, 429)

    def test_the_plan_is_read_from_the_database_not_the_loaded_row(self) -> None:
        """A webhook that upgrades mid-request must be honoured immediately.

        Authentication loads the row; the Stripe webhook commits an upgrade a
        moment later. The reservation must spend the new plan's allowance, not
        the free one the request started with.
        """
        user = self.given_user(total_generations=1)  # free, and over its limit
        request = Request({"type": "http", "headers": [], "method": "POST"})
        with self.Session() as session:
            loaded = (
                session.query(User)
                .filter_by(clerk_user_id=user.clerk_user_id)
                .one()
            )
            with self.Session() as webhook:
                webhook.query(User).filter_by(
                    clerk_user_id=user.clerk_user_id
                ).update({"plan": PLAN_MONTHLY})
                webhook.commit()
            self.assertEqual(loaded.plan, PLAN_FREE, "the loaded row is stale")

            reservation = reserve_generation(request, user=loaded, db=session)
        self.assertEqual(reservation.plan, PLAN_MONTHLY)
        self.assertEqual(self.counters(user), (2, 1, TODAY))


class TestRefund(LimitsTestCase):
    """A failed generation gives the slot back."""

    def test_refund_restores_the_free_paper(self) -> None:
        user = self.given_user()
        self.reserve(user).refund()
        self.assertEqual(self.counters(user), (0, 0, TODAY))
        # And the free paper is usable again.
        self.assertEqual(self.reserve(user).total_generations, 1)

    def test_refund_is_idempotent(self) -> None:
        user = self.given_user(total_generations=0)
        reservation = self.reserve(user)
        reservation.refund()
        reservation.refund()
        self.assertTrue(reservation.refunded)
        self.assertEqual(self.counters(user), (0, 0, TODAY))

    def test_refund_never_goes_below_zero(self) -> None:
        user = self.given_user()
        reservation = self.reserve(user)
        with self.Session() as s:  # someone else zeroed the counters
            s.query(User).filter_by(clerk_user_id=user.clerk_user_id).update(
                {"total_generations": 0, "day_generations": 0}
            )
            s.commit()
        reservation.refund()
        self.assertEqual(self.counters(user)[:2], (0, 0))

    def test_a_refund_after_midnight_leaves_todays_count_alone(self) -> None:
        """The slot came out of yesterday; today's allowance is not a piggy bank."""
        user = self.given_user(plan=PLAN_MONTHLY, clerk_user_id="user_rollover")
        reservation = self.reserve(user)  # taken on TODAY
        self.today = TOMORROW
        self.reserve(user)  # rebases day_generations to 1 for TOMORROW
        reservation.refund()
        total, day, day_date = self.counters(user)
        self.assertEqual((total, day, day_date), (1, 1, TOMORROW))


class TestConcurrency(LimitsTestCase):
    """Ten requests at once, one free paper."""

    def test_ten_concurrent_requests_yield_exactly_one_success(self) -> None:
        user = self.given_user(clerk_user_id="user_race", email="race@example.com")
        token = self.token_for(user)

        def attempt(_: int) -> int:
            # A client per thread: TestClient is not built for sharing.
            client = TestClient(app)
            return client.post(
                "/api/generate-paper", json=PAPER_BODY, headers=auth_header(token)
            ).status_code

        with ThreadPoolExecutor(max_workers=10) as pool:
            codes = list(pool.map(attempt, range(10)))

        self.assertEqual(codes.count(200), 1, f"expected one winner, got {codes}")
        self.assertEqual(codes.count(402), 9, f"expected nine refusals, got {codes}")
        self.assertEqual(self.counters(user), (1, 1, TODAY))

    def test_ten_concurrent_reservations_for_a_monthly_user_all_fit(self) -> None:
        """The lock serialises; it does not lose increments."""
        user = self.given_user(
            clerk_user_id="user_race_monthly",
            email="racem@example.com",
            plan=PLAN_MONTHLY,
        )

        def attempt(_: int) -> bool:
            try:
                self.reserve(user)
                return True
            except HTTPException:
                return False

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(attempt, range(12)))

        self.assertEqual(results.count(True), 10)
        self.assertEqual(results.count(False), 2)
        self.assertEqual(self.counters(user), (10, 10, TODAY))


class TestAbandonedRequests(LimitsTestCase):
    """A paper nobody receives must not be charged for."""

    def test_a_disconnected_client_is_not_charged(self) -> None:
        """Uvicorn finishes the paper and bins the response; refund it."""
        user = self.given_user()
        reservation = self.reserve(user)
        self.assertEqual(self.counters(user)[:2], (1, 1))

        paper = asyncio.run(self.endpoint(reservation, self.gone))

        self.assertGreater(len(paper.questions), 0, "the paper was still built")
        self.assertEqual(
            self.counters(user)[:2], (0, 0), "a paper nobody got is not charged"
        )

    def test_a_connected_client_is_charged(self) -> None:
        """The control: the same path, with someone still on the other end."""
        user = self.given_user()
        reservation = self.reserve(user)

        asyncio.run(self.endpoint(reservation, self.still_connected))

        self.assertFalse(reservation.refunded)
        self.assertEqual(self.counters(user)[:2], (1, 1))

    def test_a_cancelled_request_refunds_the_slot(self) -> None:
        """CancelledError is a BaseException, so only `finally` catches it.

        Servers other than uvicorn do cancel a request when its client goes, and
        a shutdown mid-generation cancels too. The `await` lives inside the
        route's own `try` precisely so this is survivable.
        """
        user = self.given_user()
        reservation = self.reserve(user)

        real_build = main.build_paper

        def slow_build(req):
            time.sleep(0.3)
            return real_build(req)

        async def cancel_mid_generation() -> None:
            task = asyncio.create_task(self.endpoint(reservation, self.still_connected))
            await asyncio.sleep(0.05)  # let it get into the assembler
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        main.build_paper = slow_build
        try:
            asyncio.run(cancel_mid_generation())
        finally:
            main.build_paper = real_build

        self.assertTrue(reservation.refunded)
        self.assertEqual(self.counters(user)[:2], (0, 0))


class TestGeneratePaperLimits(LimitsTestCase):
    """What the frontend actually sees."""

    def post(self, user: User, client: TestClient | None = None):
        return (client or self.client).post(
            "/api/generate-paper",
            json=PAPER_BODY,
            headers=auth_header(self.token_for(user)),
        )

    def test_free_first_paper_is_200_and_second_is_402(self) -> None:
        user = self.given_user()
        first = self.post(user)
        self.assertEqual(first.status_code, 200)
        self.assertGreater(len(first.json()["questions"]), 0)

        second = self.post(user)
        self.assertEqual(second.status_code, 402)
        self.assertEqual(second.json(), {"detail": {"code": "upgrade_required"}})
        self.assertEqual(self.counters(user), (1, 1, TODAY))

    def test_monthly_over_the_daily_cap_is_429(self) -> None:
        user = self.given_user(
            clerk_user_id="user_m_http",
            email="mhttp@example.com",
            plan=PLAN_MONTHLY,
            day_generations=9,
            day_date=TODAY,
        )
        tenth = self.post(user)
        self.assertEqual(tenth.status_code, 200)

        eleventh = self.post(user)
        self.assertEqual(eleventh.status_code, 429)
        self.assertEqual(eleventh.json(), {"detail": {"code": "daily_limit_reached"}})

    def test_a_failed_generation_is_refunded(self) -> None:
        user = self.given_user()

        def explode(req):
            raise RuntimeError("assembler fell over")

        real = main.build_paper
        main.build_paper = explode
        try:
            response = self.post(user, client=self.failing_client)
        finally:
            main.build_paper = real

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            self.counters(user), (0, 0, TODAY), "a crash must not cost the free paper"
        )
        # Which means the free paper still works.
        self.assertEqual(self.post(user).status_code, 200)

    def test_an_invalid_body_is_refunded(self) -> None:
        """422 is a failed generation too — dependencies run before validation."""
        user = self.given_user()
        response = self.client.post(
            "/api/generate-paper",
            json={"target_marks": -1},
            headers=auth_header(self.token_for(user)),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.counters(user)[:2], (0, 0))
        self.assertEqual(self.post(user).status_code, 200)

    def test_unauthenticated_requests_reserve_nothing(self) -> None:
        response = self.client.post("/api/generate-paper", json=PAPER_BODY)
        self.assertEqual(response.status_code, 401)
        with self.Session() as s:
            self.assertEqual(s.query(User).count(), 0)

    def test_me_reports_the_usage_the_limit_counted(self) -> None:
        user = self.given_user()
        self.post(user)
        body = self.client.get(
            "/api/me", headers=auth_header(self.token_for(user))
        ).json()
        self.assertEqual(body["total_generations"], 1)
        self.assertEqual(body["day_generations"], 1)
        self.assertEqual((body["free_limit"], body["daily_limit"]), (1, 10))

    def test_rendering_a_pdf_does_not_reserve_a_slot(self) -> None:
        """Re-downloading a paper you already have is free."""
        user = self.given_user(total_generations=1, day_generations=1, day_date=TODAY)
        response = self.client.post(
            "/api/render-pdf",
            json={"html": "<p>x</p>", "css": "", "filename": "paper.pdf"},
            headers=auth_header(self.token_for(user)),
        )
        self.assertNotIn(response.status_code, (402, 429))
        self.assertEqual(self.counters(user), (1, 1, TODAY))


class TestAttemptCap(LimitsTestCase):
    """The abuse ceiling: 20 started generations a day, every plan, no refunds.

    `day_generations` cannot bound work done, because a generation that fails
    or whose client disappears is refunded — so generate → disconnect → repeat
    costs nothing and can run forever. `day_attempts` is the counter that is
    spent when a slot is reserved, before any work starts, and never given
    back. A request refused before it reserves anything starts no work, so it
    moves no counter at all.
    """

    def loop(self, user: User, times: int) -> None:
        """Generate-then-abandon, the way a looping script would."""
        for _ in range(times):
            self.reserve(user).refund()

    def assert_too_many(self, user: User) -> None:
        with self.assertRaises(HTTPException) as caught:
            self.reserve(user)
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.detail, {"code": "too_many_attempts"})

    def test_a_free_user_is_capped_on_the_twenty_first_attempt(self) -> None:
        """Twenty refunded generations still spend twenty attempts."""
        user = self.given_user()
        self.loop(user, 20)
        self.assertEqual(self.attempts(user), (20, TODAY))
        self.assertEqual(
            self.counters(user)[0], 0, "every generation was refunded"
        )

        self.assert_too_many(user)
        self.assertEqual(self.counters(user)[0], 0)

    def test_a_monthly_user_is_capped_on_the_twenty_first_attempt(self) -> None:
        """The ceiling applies to a paying account too — it is not an allowance.

        A subscriber's fair-use cap of ten would normally bite first; looping
        with refunds keeps `day_generations` at zero, so the attempt cap is
        what stops it, and it answers `too_many_attempts` rather than
        `daily_limit_reached`.
        """
        user = self.given_user(
            clerk_user_id="user_cap_monthly",
            email="capm@example.com",
            plan=PLAN_MONTHLY,
        )
        self.loop(user, 20)
        self.assertEqual(self.attempts(user), (20, TODAY))
        self.assertEqual(self.counters(user)[:2], (0, 0))

        self.assert_too_many(user)

    def test_a_disconnected_generation_still_counts_as_an_attempt(self) -> None:
        """The hole this cap closes: the paper is refunded, the attempt is not."""
        user = self.given_user()
        reservation = self.reserve(user)

        asyncio.run(self.endpoint(reservation, self.gone))

        self.assertTrue(reservation.refunded)
        self.assertEqual(
            self.counters(user)[:2], (0, 0), "a paper nobody got is not charged"
        )
        self.assertEqual(
            self.attempts(user), (1, TODAY), "but the work was still done"
        )

    def test_refund_does_not_return_the_attempt(self) -> None:
        user = self.given_user()
        self.reserve(user).refund()
        self.assertEqual(self.attempts(user), (1, TODAY))

    def test_the_next_london_day_resets_the_count(self) -> None:
        user = self.given_user(day_attempts=20, attempt_date=TODAY)
        self.assert_too_many(user)

        self.today = TOMORROW
        reservation = self.reserve(user)
        self.assertEqual(reservation.day_attempts, 1)
        self.assertEqual(self.attempts(user), (1, TOMORROW))

    def test_a_stale_attempt_date_is_rebased_not_added_to(self) -> None:
        """Yesterday's twenty do not count against today."""
        user = self.given_user(
            day_attempts=20, attempt_date=TODAY - timedelta(days=1)
        )
        self.assertEqual(self.reserve(user).day_attempts, 1)
        self.assertEqual(self.attempts(user), (1, TODAY))

    def test_the_cap_outranks_the_free_limit(self) -> None:
        """A looping free user is told to stop, not told to pay."""
        user = self.given_user(
            total_generations=1, day_attempts=20, attempt_date=TODAY
        )
        self.assert_too_many(user)

    def test_a_refused_generation_spends_no_attempt(self) -> None:
        """402 reserves nothing, so it starts no work and costs no attempt.

        Only a reserved slot counts. Charging for the refusal would let a free
        user who has spent their paper burn through the day's attempts without
        any compute being done on their behalf.
        """
        user = self.given_user(total_generations=1)  # free, and already spent
        with self.assertRaises(HTTPException) as caught:
            self.reserve(user)
        self.assertEqual(caught.exception.status_code, 402)
        self.assertEqual(self.attempts(user), (0, None))

    def test_a_refused_generation_leaves_a_stale_attempt_date_alone(self) -> None:
        """Yesterday's count is not rebased by a request that reserved nothing."""
        yesterday = TODAY - timedelta(days=1)
        user = self.given_user(
            total_generations=1, day_attempts=7, attempt_date=yesterday
        )
        with self.assertRaises(HTTPException) as caught:
            self.reserve(user)
        self.assertEqual(caught.exception.status_code, 402)
        self.assertEqual(self.attempts(user), (7, yesterday))

    def test_a_free_user_refused_all_day_can_generate_once_upgraded(self) -> None:
        """Twenty 402s must not cost the day they finally pay.

        The free paper is spent, so every request is refused and reserves
        nothing. If those refusals counted, the upgrade would land on an
        account already at the ceiling and the first paying generation would be
        a 429 — exactly the user we least want to turn away.
        """
        user = self.given_user(total_generations=1)  # free, and already spent
        for _ in range(20):
            with self.assertRaises(HTTPException) as caught:
                self.reserve(user)
            self.assertEqual(caught.exception.status_code, 402)
        self.assertEqual(self.attempts(user), (0, None))

        with self.Session() as webhook:  # Stripe says they subscribed
            webhook.query(User).filter_by(
                clerk_user_id=user.clerk_user_id
            ).update({"plan": PLAN_MONTHLY})
            webhook.commit()

        reservation = self.reserve(user)
        self.assertEqual(reservation.plan, PLAN_MONTHLY)
        self.assertEqual(reservation.day_generations, 1)
        self.assertEqual(reservation.day_attempts, 1)
        self.assertEqual(self.attempts(user), (1, TODAY))

    def test_an_attempt_over_the_cap_adds_nothing(self) -> None:
        """The one refusal that costs nothing, so a loop cannot top itself up."""
        user = self.given_user(day_attempts=20, attempt_date=TODAY)
        for _ in range(3):
            self.assert_too_many(user)
        self.assertEqual(self.attempts(user), (20, TODAY))

    def test_the_cap_follows_the_environment(self) -> None:
        os.environ["MAX_DAILY_ATTEMPTS"] = "2"
        get_settings.cache_clear()
        user = self.given_user()
        self.loop(user, 2)
        self.assert_too_many(user)

    def test_over_http_the_body_is_too_many_attempts(self) -> None:
        """What the frontend keys off: a 429 with its own code, and no upsell."""
        user = self.given_user(day_attempts=20, attempt_date=TODAY)
        response = self.client.post(
            "/api/generate-paper",
            json=PAPER_BODY,
            headers=auth_header(self.token_for(user)),
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {"detail": {"code": "too_many_attempts"}})
        self.assertEqual(self.counters(user)[0], 0)

    def test_concurrent_attempts_do_not_overshoot_the_cap(self) -> None:
        """The attempt counter is as race-proof as the generation counter."""
        user = self.given_user(
            clerk_user_id="user_cap_race",
            email="capr@example.com",
            plan=PLAN_MONTHLY,
            day_attempts=18,
            attempt_date=TODAY,
        )

        def attempt(_: int) -> bool:
            try:
                self.reserve(user)
                return True
            except HTTPException as exc:
                self.assertEqual(exc.detail, {"code": "too_many_attempts"})
                return False

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(attempt, range(6)))

        self.assertEqual(results.count(True), 2, f"expected two to fit: {results}")
        self.assertEqual(self.attempts(user), (20, TODAY))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
