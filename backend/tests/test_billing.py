"""Stripe checkout, portal and webhook, against a mocked Stripe.

Nothing here touches the network. The two API calls go through seams in
`app.billing` that each test replaces, and the webhook tests sign their own
payloads with a throwaway secret so the **real** signature verification runs —
that check is the webhook's entire authentication, so faking it would test
nothing.

`setUp` overwrites every Stripe env var with an obvious dummy, so a test that
accidentally reaches the SDK cannot reach the real account.

Needs `TEST_DATABASE_URL`: these tests create and drop tables, so they refuse
to touch `DATABASE_URL`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import unittest
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
import stripe
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import auth, billing
from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import PLAN_FREE, PLAN_MONTHLY, StripeEvent, User
from tests.fake_clerk import PUBLIC_KEY, auth_header, make_token

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

WEBHOOK_SECRET = "whsec_test_secret_for_tests_only"
PRICE_ID = "price_test_monthly"
FRONTEND = "http://localhost:5173"

CUSTOMER_ID = "cus_test_123"
SUBSCRIPTION_ID = "sub_test_123"


class FakeStripeSession:
    """What the SDK hands back: we only ever read `.url`."""

    def __init__(self, url: str = "https://checkout.stripe.test/session") -> None:
        self.url = url


def sign(payload: bytes, secret: str = WEBHOOK_SECRET, age: int = 0) -> str:
    """A `Stripe-Signature` header, built the way Stripe documents it."""
    timestamp = int(time.time()) - age
    signed = b"%d.%s" % (timestamp, payload)
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def event_payload(
    event_type: str, obj: dict[str, Any], event_id: str = "evt_test_1"
) -> bytes:
    """A Stripe event, serialised exactly as it will be signed."""
    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": event_type,
            "data": {"object": obj},
        }
    ).encode()


def checkout_session_object(
    client_reference_id: str | None,
    customer: Any = CUSTOMER_ID,
    subscription: Any = SUBSCRIPTION_ID,
    payment_status: str | None = "paid",
) -> dict[str, Any]:
    """A completed Checkout session. `payment_status=None` omits the field."""
    obj: dict[str, Any] = {
        "id": "cs_test_123",
        "object": "checkout.session",
        "client_reference_id": client_reference_id,
        "customer": customer,
        "subscription": subscription,
        "mode": "subscription",
        "status": "complete",
    }
    if payment_status is not None:
        obj["payment_status"] = payment_status
    return obj


#: 7 November 2026, 09:00 UTC — a period end to assert against.
PERIOD_END = 1794042000
#: A month later, for the "latest item wins" case.
LATER_PERIOD_END = 1796634000

#: Tells the fixture below to leave a field out altogether, so that passing
#: `None` can mean the explicit JSON `null` Stripe sends on a renewal.
OMIT = object()


def subscription_object(
    status: str,
    subscription_id: str = SUBSCRIPTION_ID,
    *,
    cancel_at: Any = OMIT,
    cancel_at_period_end: Any = OMIT,
    item_period_ends: Any = OMIT,
    period_end: Any = OMIT,
) -> dict[str, Any]:
    """A subscription, with the cancel fields present only when asked for.

    `item_period_ends` puts a `current_period_end` on each entry of
    `items.data[]`, where current Stripe API versions keep it; `period_end` puts
    a single one at the top level, where older versions kept it. A webhook
    delivery uses the endpoint's API version, so a test exists for each.
    """
    obj: dict[str, Any] = {
        "id": subscription_id,
        "object": "subscription",
        "status": status,
        "customer": CUSTOMER_ID,
    }
    if cancel_at is not OMIT:
        obj["cancel_at"] = cancel_at
    if cancel_at_period_end is not OMIT:
        obj["cancel_at_period_end"] = cancel_at_period_end
    if item_period_ends is not OMIT:
        obj["items"] = {
            "object": "list",
            "data": [
                {"id": f"si_test_{i}", "current_period_end": end}
                for i, end in enumerate(item_period_ends)
            ],
        }
    if period_end is not OMIT:
        obj["current_period_end"] = period_end
    return obj


def utc(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL to a throwaway Postgres to run these "
    "(they create and drop tables)",
)
class BillingTestCase(unittest.TestCase):
    """A test database, Clerk tokens, and a Stripe that never leaves the process."""

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
        cls.failing_client = TestClient(app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()

    def setUp(self) -> None:
        with self.Session() as s:
            s.query(User).delete()
            s.query(StripeEvent).delete()
            s.commit()

        self._real_signing_key = auth.signing_key
        auth.signing_key = lambda token: PUBLIC_KEY

        # Obvious dummies: a stray real call cannot touch the real account.
        self._previous_env = {
            name: os.environ.get(name)
            for name in (
                "STRIPE_SECRET_KEY",
                "STRIPE_WEBHOOK_SECRET",
                "STRIPE_PRICE_MONTHLY",
                "FRONTEND_URL",
                "AUTHORIZED_PARTIES",
            )
        }
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy_not_a_real_key"
        os.environ["STRIPE_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        os.environ["STRIPE_PRICE_MONTHLY"] = PRICE_ID
        os.environ["FRONTEND_URL"] = FRONTEND
        os.environ["AUTHORIZED_PARTIES"] = FRONTEND
        get_settings.cache_clear()

        # Record what we would have asked Stripe for.
        self.checkout_calls: list[dict[str, Any]] = []
        self.portal_calls: list[dict[str, Any]] = []
        self._real_checkout = billing.create_checkout_session
        self._real_portal = billing.create_portal_session

        def fake_checkout(**params: Any) -> FakeStripeSession:
            self.checkout_calls.append(params)
            return FakeStripeSession("https://checkout.stripe.test/session")

        def fake_portal(**params: Any) -> FakeStripeSession:
            self.portal_calls.append(params)
            return FakeStripeSession("https://portal.stripe.test/session")

        billing.create_checkout_session = fake_checkout
        billing.create_portal_session = fake_portal

    def tearDown(self) -> None:
        auth.signing_key = self._real_signing_key
        billing.create_checkout_session = self._real_checkout
        billing.create_portal_session = self._real_portal
        for name, value in self._previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        get_settings.cache_clear()

    # --- fixtures -----------------------------------------------------------

    def given_user(
        self,
        *,
        clerk_user_id: str = "user_billing",
        email: str = "billing@example.com",
        plan: str = PLAN_FREE,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        subscription_status: str | None = None,
        cancel_at: datetime | None = None,
    ) -> User:
        with self.Session() as s:
            user = User(
                clerk_user_id=clerk_user_id,
                email=email,
                plan=plan,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription_id,
                subscription_status=subscription_status,
                cancel_at=cancel_at,
            )
            s.add(user)
            s.commit()
            return user

    def row(self, user: User) -> User:
        with self.Session() as s:
            return s.query(User).filter_by(clerk_user_id=user.clerk_user_id).one()

    def event_ids(self) -> list[str]:
        with self.Session() as s:
            return [e.id for e in s.query(StripeEvent).all()]

    def headers(self, user: User) -> dict[str, str]:
        return auth_header(make_token(sub=user.clerk_user_id, email=user.email))

    def deliver(
        self, payload: bytes, signature: str | None = None, client: TestClient | None = None
    ):
        """POST a webhook delivery, signed unless told otherwise."""
        headers = {"Content-Type": "application/json"}
        if signature is None:
            signature = sign(payload)
        if signature:
            headers["Stripe-Signature"] = signature
        return (client or self.client).post(
            "/api/stripe/webhook", content=payload, headers=headers
        )


class TestCheckout(BillingTestCase):
    def test_requires_auth(self) -> None:
        response = self.client.post("/api/billing/checkout")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "auth_required")
        self.assertEqual(self.checkout_calls, [])

    def test_returns_the_session_url(self) -> None:
        user = self.given_user()
        response = self.client.post("/api/billing/checkout", headers=self.headers(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"url": "https://checkout.stripe.test/session"}
        )

    def test_session_parameters_are_exactly_as_specified(self) -> None:
        user = self.given_user()
        self.client.post("/api/billing/checkout", headers=self.headers(user))

        self.assertEqual(len(self.checkout_calls), 1)
        params = self.checkout_calls[0]
        self.assertEqual(params["mode"], "subscription")
        self.assertEqual(params["line_items"], [{"price": PRICE_ID, "quantity": 1}])
        self.assertEqual(params["client_reference_id"], str(self.row(user).id))
        self.assertEqual(params["success_url"], f"{FRONTEND}/account?upgraded=1")
        self.assertEqual(params["cancel_url"], f"{FRONTEND}/pricing")

    def test_a_user_with_no_customer_is_identified_by_email(self) -> None:
        user = self.given_user(email="newcustomer@example.com")
        self.client.post("/api/billing/checkout", headers=self.headers(user))
        params = self.checkout_calls[0]
        self.assertEqual(params["customer_email"], "newcustomer@example.com")
        self.assertNotIn("customer", params)

    def test_an_existing_customer_is_reused(self) -> None:
        """A resubscribe must not create a second Stripe customer."""
        user = self.given_user(stripe_customer_id=CUSTOMER_ID)
        self.client.post("/api/billing/checkout", headers=self.headers(user))
        params = self.checkout_calls[0]
        self.assertEqual(params["customer"], CUSTOMER_ID)
        self.assertNotIn("customer_email", params)

    def test_a_subscriber_gets_409_already_subscribed(self) -> None:
        user = self.given_user(plan=PLAN_MONTHLY, subscription_status="active")
        response = self.client.post("/api/billing/checkout", headers=self.headers(user))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": {"code": "already_subscribed"}})
        self.assertEqual(self.checkout_calls, [], "Stripe must not be called")

    def test_a_missing_price_is_503_not_a_crash(self) -> None:
        del os.environ["STRIPE_PRICE_MONTHLY"]
        get_settings.cache_clear()
        user = self.given_user()
        with self.assertLogs("app.billing", level="ERROR") as captured:
            response = self.client.post(
                "/api/billing/checkout", headers=self.headers(user)
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": {"code": "billing_unavailable"}})
        self.assertEqual(self.checkout_calls, [])
        self.assertTrue(any("STRIPE_PRICE_MONTHLY" in line for line in captured.output))

    def test_a_missing_secret_key_is_503_and_never_calls_stripe(self) -> None:
        """Exercises the real seam: no key, so the SDK is never reached."""
        billing.create_checkout_session = self._real_checkout
        del os.environ["STRIPE_SECRET_KEY"]
        get_settings.cache_clear()
        user = self.given_user()
        with self.assertLogs("app.billing", level="ERROR") as captured:
            response = self.client.post(
                "/api/billing/checkout", headers=self.headers(user)
            )
        self.assertEqual(response.status_code, 503)
        self.assertTrue(any("STRIPE_SECRET_KEY" in line for line in captured.output))

    def test_a_stripe_error_is_503(self) -> None:
        def explode(**params: Any) -> FakeStripeSession:
            raise stripe.StripeError("Stripe is having a day")

        billing.create_checkout_session = explode
        user = self.given_user()
        with self.assertLogs("app.billing", level="ERROR"):
            response = self.client.post(
                "/api/billing/checkout", headers=self.headers(user)
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": {"code": "billing_unavailable"}})


class TestPortal(BillingTestCase):
    def test_requires_auth(self) -> None:
        response = self.client.post("/api/billing/portal")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.portal_calls, [])

    def test_no_customer_is_400_no_customer(self) -> None:
        user = self.given_user()
        response = self.client.post("/api/billing/portal", headers=self.headers(user))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": {"code": "no_customer"}})
        self.assertEqual(self.portal_calls, [], "Stripe must not be called")

    def test_returns_the_portal_url(self) -> None:
        user = self.given_user(
            plan=PLAN_MONTHLY, stripe_customer_id=CUSTOMER_ID, subscription_status="active"
        )
        response = self.client.post("/api/billing/portal", headers=self.headers(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"url": "https://portal.stripe.test/session"})
        self.assertEqual(
            self.portal_calls,
            [{"customer": CUSTOMER_ID, "return_url": f"{FRONTEND}/account"}],
        )

    def test_a_stripe_error_is_503(self) -> None:
        def explode(**params: Any) -> FakeStripeSession:
            raise stripe.StripeError("nope")

        billing.create_portal_session = explode
        user = self.given_user(stripe_customer_id=CUSTOMER_ID)
        with self.assertLogs("app.billing", level="ERROR"):
            response = self.client.post(
                "/api/billing/portal", headers=self.headers(user)
            )
        self.assertEqual(response.status_code, 503)


class TestWebhookSignature(BillingTestCase):
    """The signature is the webhook's only authentication."""

    def test_a_correctly_signed_delivery_is_accepted(self) -> None:
        payload = event_payload("invoice.paid", {"id": "in_1", "object": "invoice"})
        self.assertEqual(self.deliver(payload).status_code, 200)

    def test_needs_no_authorization_header(self) -> None:
        payload = event_payload("invoice.paid", {"id": "in_2", "object": "invoice"})
        response = self.deliver(payload)
        self.assertEqual(response.status_code, 200)

    def test_a_bad_signature_is_400(self) -> None:
        payload = event_payload("checkout.session.completed", checkout_session_object(None))
        response = self.deliver(payload, signature=sign(payload, secret="whsec_wrong"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.event_ids(), [], "an unverified event is not recorded")

    def test_a_missing_signature_header_is_400(self) -> None:
        payload = event_payload("invoice.paid", {"id": "in_3", "object": "invoice"})
        self.assertEqual(self.deliver(payload, signature="").status_code, 400)

    def test_a_tampered_body_is_400(self) -> None:
        """The signature covers the raw bytes, so editing them invalidates it."""
        payload = event_payload("invoice.paid", {"id": "in_4", "object": "invoice"})
        signature = sign(payload)
        response = self.deliver(payload.replace(b"in_4", b"in_5"), signature=signature)
        self.assertEqual(response.status_code, 400)

    def test_a_stale_timestamp_is_400(self) -> None:
        """Replay protection: Stripe's default tolerance is five minutes."""
        payload = event_payload("invoice.paid", {"id": "in_6", "object": "invoice"})
        response = self.deliver(payload, signature=sign(payload, age=3600))
        self.assertEqual(response.status_code, 400)

    def test_a_missing_webhook_secret_rejects_everything(self) -> None:
        del os.environ["STRIPE_WEBHOOK_SECRET"]
        get_settings.cache_clear()
        payload = event_payload("invoice.paid", {"id": "in_7", "object": "invoice"})
        with self.assertLogs("app.billing", level="ERROR") as captured:
            response = self.deliver(payload)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(
            any("STRIPE_WEBHOOK_SECRET" in line for line in captured.output),
            f"expected the variable named in the log, got {captured.output}",
        )


class TestWebhookCheckoutCompleted(BillingTestCase):
    def test_grants_the_monthly_plan(self) -> None:
        user = self.given_user()
        payload = event_payload(
            "checkout.session.completed",
            checkout_session_object(str(self.row(user).id)),
        )
        response = self.deliver(payload)

        self.assertEqual(response.status_code, 200)
        fresh = self.row(user)
        self.assertEqual(fresh.plan, PLAN_MONTHLY)
        self.assertEqual(fresh.subscription_status, "active")
        self.assertEqual(fresh.stripe_customer_id, CUSTOMER_ID)
        self.assertEqual(fresh.stripe_subscription_id, SUBSCRIPTION_ID)

    def test_accepts_expanded_customer_and_subscription_objects(self) -> None:
        """Stripe sends these as ids or as whole objects depending on expansion."""
        user = self.given_user()
        payload = event_payload(
            "checkout.session.completed",
            checkout_session_object(
                str(self.row(user).id),
                customer={"id": CUSTOMER_ID, "object": "customer"},
                subscription={"id": SUBSCRIPTION_ID, "object": "subscription"},
            ),
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        fresh = self.row(user)
        self.assertEqual(fresh.stripe_customer_id, CUSTOMER_ID)
        self.assertEqual(fresh.stripe_subscription_id, SUBSCRIPTION_ID)

    def test_an_unknown_reference_is_acknowledged_not_retried(self) -> None:
        """`stripe trigger` sends fixtures with no user of ours attached."""
        self.given_user()
        payload = event_payload(
            "checkout.session.completed", checkout_session_object(str(uuid.uuid4()))
        )
        with self.assertLogs("app.billing", level="WARNING"):
            response = self.deliver(payload)
        self.assertEqual(response.status_code, 200)

    def test_a_missing_reference_is_acknowledged(self) -> None:
        payload = event_payload("checkout.session.completed", checkout_session_object(None))
        with self.assertLogs("app.billing", level="WARNING"):
            self.assertEqual(self.deliver(payload).status_code, 200)

    def test_a_nonsense_reference_is_acknowledged(self) -> None:
        payload = event_payload(
            "checkout.session.completed", checkout_session_object("not-a-uuid")
        )
        with self.assertLogs("app.billing", level="WARNING"):
            self.assertEqual(self.deliver(payload).status_code, 200)

    def test_an_unpaid_session_grants_nothing_but_keeps_the_ids(self) -> None:
        """Completing Checkout is not paying for it.

        An asynchronous payment method finishes the session now and settles
        later. The ids are worth keeping — they are how the subscription events
        find this user — but the plan waits.
        """
        user = self.given_user()
        payload = event_payload(
            "checkout.session.completed",
            checkout_session_object(str(self.row(user).id), payment_status="unpaid"),
            event_id="evt_unpaid",
        )
        response = self.deliver(payload)

        self.assertEqual(response.status_code, 200)
        fresh = self.row(user)
        self.assertEqual(fresh.plan, PLAN_FREE, "unpaid must not grant the plan")
        self.assertIsNone(fresh.subscription_status)
        self.assertEqual(fresh.stripe_customer_id, CUSTOMER_ID)
        self.assertEqual(fresh.stripe_subscription_id, SUBSCRIPTION_ID)

    def test_an_unpaid_session_is_granted_once_the_subscription_goes_active(
        self,
    ) -> None:
        """The handoff: the ids stored above are what makes this match."""
        user = self.given_user()
        self.deliver(
            event_payload(
                "checkout.session.completed",
                checkout_session_object(str(self.row(user).id), payment_status="unpaid"),
                event_id="evt_unpaid_then_active",
            )
        )
        self.assertEqual(self.row(user).plan, PLAN_FREE)

        self.deliver(
            event_payload(
                "customer.subscription.updated",
                subscription_object("active"),
                event_id="evt_now_active",
            )
        )
        fresh = self.row(user)
        self.assertEqual(fresh.plan, PLAN_MONTHLY)
        self.assertEqual(fresh.subscription_status, "active")

    def test_an_unpaid_session_that_never_settles_stays_free(self) -> None:
        user = self.given_user()
        self.deliver(
            event_payload(
                "checkout.session.completed",
                checkout_session_object(str(self.row(user).id), payment_status="unpaid"),
                event_id="evt_never_settles",
            )
        )
        self.deliver(
            event_payload(
                "customer.subscription.updated",
                subscription_object("incomplete_expired"),
                event_id="evt_expired",
            )
        )
        fresh = self.row(user)
        self.assertEqual(fresh.plan, PLAN_FREE)
        self.assertEqual(fresh.subscription_status, "incomplete_expired")

    def test_no_payment_required_grants_access(self) -> None:
        """A full-discount or card-less trial is settled, not unpaid."""
        user = self.given_user()
        payload = event_payload(
            "checkout.session.completed",
            checkout_session_object(
                str(self.row(user).id), payment_status="no_payment_required"
            ),
            event_id="evt_free_trial",
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        self.assertEqual(self.row(user).plan, PLAN_MONTHLY)

    def test_a_session_with_no_payment_status_grants_nothing(self) -> None:
        """Cautious on a missing field: the subscription event still follows."""
        user = self.given_user()
        payload = event_payload(
            "checkout.session.completed",
            checkout_session_object(str(self.row(user).id), payment_status=None),
            event_id="evt_no_status",
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        self.assertEqual(self.row(user).plan, PLAN_FREE)
        self.assertEqual(self.row(user).stripe_subscription_id, SUBSCRIPTION_ID)

    def test_the_success_redirect_grants_nothing_on_its_own(self) -> None:
        """Only the webhook upgrades a plan; the browser's return URL cannot."""
        user = self.given_user()
        self.client.get("/api/me", headers=self.headers(user))
        self.assertEqual(self.row(user).plan, PLAN_FREE)


class TestSubscriptionCancelAt(unittest.TestCase):
    """`subscription_cancel_at` on its own. No database, no Stripe, no HTTP."""

    def test_an_explicit_cancel_at_is_read_as_utc(self) -> None:
        obj = subscription_object("active", cancel_at=PERIOD_END)
        self.assertEqual(billing.subscription_cancel_at(obj), utc(PERIOD_END))

    def test_an_explicit_cancel_at_beats_the_period_end(self) -> None:
        """Stripe sends both when a cancel is set for a specific date."""
        obj = subscription_object(
            "active",
            cancel_at=PERIOD_END,
            cancel_at_period_end=True,
            item_period_ends=[LATER_PERIOD_END],
        )
        self.assertEqual(billing.subscription_cancel_at(obj), utc(PERIOD_END))

    def test_period_end_comes_from_the_item(self) -> None:
        obj = subscription_object(
            "active", cancel_at_period_end=True, item_period_ends=[PERIOD_END]
        )
        self.assertEqual(billing.subscription_cancel_at(obj), utc(PERIOD_END))

    def test_period_end_falls_back_to_the_top_level(self) -> None:
        """An older API version on the webhook endpoint sends only this."""
        obj = subscription_object(
            "active", cancel_at_period_end=True, period_end=PERIOD_END
        )
        self.assertEqual(billing.subscription_cancel_at(obj), utc(PERIOD_END))

    def test_the_item_wins_over_the_top_level(self) -> None:
        obj = subscription_object(
            "active",
            cancel_at_period_end=True,
            item_period_ends=[LATER_PERIOD_END],
            period_end=PERIOD_END,
        )
        self.assertEqual(billing.subscription_cancel_at(obj), utc(LATER_PERIOD_END))

    def test_the_latest_item_wins(self) -> None:
        """Several items: the subscription runs until the last of them ends."""
        obj = subscription_object(
            "active",
            cancel_at_period_end=True,
            item_period_ends=[PERIOD_END, LATER_PERIOD_END],
        )
        self.assertEqual(billing.subscription_cancel_at(obj), utc(LATER_PERIOD_END))

    def test_no_cancel_scheduled_is_none(self) -> None:
        for obj in (
            subscription_object("active"),
            subscription_object("active", cancel_at=None, cancel_at_period_end=False),
            subscription_object(
                "active", cancel_at_period_end=False, item_period_ends=[PERIOD_END]
            ),
        ):
            with self.subTest(obj=obj):
                self.assertIsNone(billing.subscription_cancel_at(obj))

    def test_garbage_is_none_and_never_raises(self) -> None:
        cases = [
            subscription_object("active", cancel_at="soon"),
            subscription_object("active", cancel_at=-1),
            subscription_object("active", cancel_at=0),
            subscription_object("active", cancel_at=True),
            subscription_object("active", cancel_at=PERIOD_END * 10**6),
            subscription_object("active", cancel_at_period_end=True),
            subscription_object("active", cancel_at_period_end=True, period_end="soon"),
            subscription_object(
                "active", cancel_at_period_end=True, item_period_ends=[]
            ),
            subscription_object(
                "active", cancel_at_period_end=True, item_period_ends=[None, "soon"]
            ),
            subscription_object("active", cancel_at_period_end="yes"),
            {"items": "not a list"},
            {"cancel_at_period_end": True, "items": {"data": "not a list"}},
            {"cancel_at_period_end": True, "items": {"data": ["not a dict"]}},
            {},
            None,
            "not an object",
        ]
        for obj in cases:
            with self.subTest(obj=obj):
                self.assertIsNone(billing.subscription_cancel_at(obj))


class TestWebhookSubscriptionUpdated(BillingTestCase):
    def subscriber(self, cancel_at: datetime | None = None) -> User:
        return self.given_user(
            plan=PLAN_MONTHLY,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            subscription_status="active",
            cancel_at=cancel_at,
        )

    def test_active_keeps_the_monthly_plan(self) -> None:
        user = self.subscriber()
        payload = event_payload(
            "customer.subscription.updated", subscription_object("active")
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        self.assertEqual(self.row(user).plan, PLAN_MONTHLY)

    def test_trialing_entitles_the_monthly_plan(self) -> None:
        user = self.given_user(
            plan=PLAN_FREE,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
        )
        payload = event_payload(
            "customer.subscription.updated", subscription_object("trialing")
        )
        self.deliver(payload)
        fresh = self.row(user)
        self.assertEqual(fresh.plan, PLAN_MONTHLY)
        self.assertEqual(fresh.subscription_status, "trialing")

    def test_past_due_drops_to_free_but_keeps_the_raw_status(self) -> None:
        user = self.subscriber()
        payload = event_payload(
            "customer.subscription.updated", subscription_object("past_due")
        )
        self.deliver(payload)
        fresh = self.row(user)
        self.assertEqual(fresh.plan, PLAN_FREE)
        self.assertEqual(fresh.subscription_status, "past_due")

    def test_an_unknown_subscription_is_acknowledged(self) -> None:
        self.subscriber()
        payload = event_payload(
            "customer.subscription.updated",
            subscription_object("active", subscription_id="sub_someone_else"),
        )
        with self.assertLogs("app.billing", level="WARNING"):
            self.assertEqual(self.deliver(payload).status_code, 200)

    def test_a_scheduled_cancel_is_stored_and_keeps_the_plan(self) -> None:
        """Cancelled but paid up: still `monthly`, with the end date recorded."""
        user = self.subscriber()
        payload = event_payload(
            "customer.subscription.updated",
            subscription_object(
                "active", cancel_at_period_end=True, item_period_ends=[PERIOD_END]
            ),
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        fresh = self.row(user)
        self.assertEqual(fresh.plan, PLAN_MONTHLY)
        self.assertEqual(fresh.subscription_status, "active")
        self.assertEqual(fresh.cancel_at, utc(PERIOD_END))

    def test_a_scheduled_cancel_from_an_older_api_version(self) -> None:
        """Only a top-level `current_period_end`: same outcome."""
        user = self.subscriber()
        payload = event_payload(
            "customer.subscription.updated",
            subscription_object(
                "active", cancel_at_period_end=True, period_end=PERIOD_END
            ),
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        fresh = self.row(user)
        self.assertEqual(fresh.plan, PLAN_MONTHLY)
        self.assertEqual(fresh.cancel_at, utc(PERIOD_END))

    def test_an_explicit_cancel_at_is_stored(self) -> None:
        user = self.subscriber()
        payload = event_payload(
            "customer.subscription.updated",
            subscription_object("active", cancel_at=PERIOD_END),
        )
        self.deliver(payload)
        self.assertEqual(self.row(user).cancel_at, utc(PERIOD_END))

    def test_renewing_clears_the_cancel_date(self) -> None:
        """The Customer Portal's "renew" button sends exactly this."""
        user = self.subscriber(cancel_at=utc(PERIOD_END))
        payload = event_payload(
            "customer.subscription.updated",
            subscription_object(
                "active",
                cancel_at=None,
                cancel_at_period_end=False,
                item_period_ends=[PERIOD_END],
            ),
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        fresh = self.row(user)
        self.assertEqual(fresh.plan, PLAN_MONTHLY)
        self.assertIsNone(fresh.cancel_at)

    def test_garbage_cancel_fields_leave_no_date_and_still_return_200(self) -> None:
        """A date we only display must never cost us the status in the same event."""
        user = self.subscriber(cancel_at=utc(PERIOD_END))
        payload = event_payload(
            "customer.subscription.updated",
            subscription_object(
                "active", cancel_at="whenever", cancel_at_period_end=True
            ),
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        fresh = self.row(user)
        self.assertEqual(fresh.plan, PLAN_MONTHLY)
        self.assertEqual(fresh.subscription_status, "active")
        self.assertIsNone(fresh.cancel_at)

    def test_a_negative_cancel_at_is_ignored(self) -> None:
        user = self.subscriber(cancel_at=utc(PERIOD_END))
        payload = event_payload(
            "customer.subscription.updated", subscription_object("active", cancel_at=-1)
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        self.assertIsNone(self.row(user).cancel_at)

    def test_a_missing_items_list_is_ignored(self) -> None:
        user = self.subscriber(cancel_at=utc(PERIOD_END))
        payload = event_payload(
            "customer.subscription.updated",
            subscription_object("active", cancel_at_period_end=True),
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        self.assertIsNone(self.row(user).cancel_at)


class TestWebhookSubscriptionDeleted(BillingTestCase):
    def test_cancellation_returns_the_account_to_free(self) -> None:
        user = self.given_user(
            plan=PLAN_MONTHLY,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            subscription_status="active",
        )
        payload = event_payload(
            "customer.subscription.deleted", subscription_object("canceled")
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        fresh = self.row(user)
        self.assertEqual(fresh.plan, PLAN_FREE)
        self.assertEqual(fresh.subscription_status, "canceled")
        self.assertEqual(
            fresh.stripe_customer_id,
            CUSTOMER_ID,
            "keep the customer id so a resubscribe reuses it",
        )

    def test_cancellation_clears_a_scheduled_cancel_date(self) -> None:
        """It has stopped, so there is no date it is going to stop on."""
        user = self.given_user(
            plan=PLAN_MONTHLY,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            subscription_status="active",
            cancel_at=utc(PERIOD_END),
        )
        payload = event_payload(
            "customer.subscription.deleted",
            subscription_object("canceled", cancel_at=PERIOD_END),
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        fresh = self.row(user)
        self.assertEqual(fresh.plan, PLAN_FREE)
        self.assertIsNone(fresh.cancel_at)


class TestWebhookIdempotency(BillingTestCase):
    def test_an_event_id_is_recorded_once(self) -> None:
        user = self.given_user()
        payload = event_payload(
            "checkout.session.completed",
            checkout_session_object(str(self.row(user).id)),
            event_id="evt_once",
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        self.assertEqual(self.event_ids(), ["evt_once"])

    def test_a_repeat_delivery_changes_nothing(self) -> None:
        """Stripe retries. The second delivery must be a no-op, not a re-apply."""
        user = self.given_user()
        payload = event_payload(
            "checkout.session.completed",
            checkout_session_object(str(self.row(user).id)),
            event_id="evt_repeat",
        )
        self.deliver(payload)

        # Someone cancels in the Stripe dashboard, so we are back to free...
        with self.Session() as s:
            s.query(User).filter_by(clerk_user_id=user.clerk_user_id).update(
                {"plan": PLAN_FREE, "subscription_status": "canceled"}
            )
            s.commit()

        # ...and Stripe redelivers the original checkout event.
        second = self.deliver(payload)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], "duplicate")
        self.assertEqual(
            self.row(user).plan, PLAN_FREE, "a replayed event must not re-grant access"
        )
        self.assertEqual(self.event_ids(), ["evt_repeat"])

    def test_an_ignored_event_type_is_acknowledged_and_recorded(self) -> None:
        payload = event_payload(
            "invoice.payment_succeeded",
            {"id": "in_ignored", "object": "invoice"},
            event_id="evt_ignored",
        )
        response = self.deliver(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ignored")
        self.assertEqual(self.event_ids(), ["evt_ignored"])

    def test_a_handler_that_raises_records_nothing(self) -> None:
        """So Stripe's retry gets a real second attempt, not a skipped one."""
        user = self.given_user()
        real = billing.HANDLERS["checkout.session.completed"]

        def explode(db, obj):
            raise RuntimeError("database went away mid-handler")

        billing.HANDLERS["checkout.session.completed"] = explode
        try:
            payload = event_payload(
                "checkout.session.completed",
                checkout_session_object(str(self.row(user).id)),
                event_id="evt_boom",
            )
            response = self.deliver(payload, client=self.failing_client)
        finally:
            billing.HANDLERS["checkout.session.completed"] = real

        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.event_ids(), [], "a failed event must be retryable")
        self.assertEqual(self.row(user).plan, PLAN_FREE)

        # The retry then works.
        payload = event_payload(
            "checkout.session.completed",
            checkout_session_object(str(self.row(user).id)),
            event_id="evt_boom",
        )
        self.assertEqual(self.deliver(payload).status_code, 200)
        self.assertEqual(self.row(user).plan, PLAN_MONTHLY)


class TestPlanReachesTheRestOfTheApp(BillingTestCase):
    """The webhook's write is what every other limit reads."""

    def test_me_reports_the_plan_the_webhook_granted(self) -> None:
        user = self.given_user()
        payload = event_payload(
            "checkout.session.completed",
            checkout_session_object(str(self.row(user).id)),
            event_id="evt_me",
        )
        self.deliver(payload)
        body = self.client.get("/api/me", headers=self.headers(user)).json()
        self.assertEqual(body["plan"], PLAN_MONTHLY)

    def test_me_reports_no_cancel_date_by_default(self) -> None:
        user = self.given_user()
        body = self.client.get("/api/me", headers=self.headers(user)).json()
        self.assertIsNone(body["cancel_at"])

    def test_me_reports_the_cancel_date_as_iso_with_an_offset(self) -> None:
        user = self.given_user(
            plan=PLAN_MONTHLY,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            subscription_status="active",
        )
        payload = event_payload(
            "customer.subscription.updated",
            subscription_object(
                "active", cancel_at_period_end=True, item_period_ends=[PERIOD_END]
            ),
            event_id="evt_me_cancel",
        )
        self.deliver(payload)
        body = self.client.get("/api/me", headers=self.headers(user)).json()
        self.assertEqual(body["plan"], PLAN_MONTHLY)
        self.assertEqual(
            datetime.fromisoformat(body["cancel_at"]).astimezone(timezone.utc),
            utc(PERIOD_END),
        )
        self.assertIsNotNone(datetime.fromisoformat(body["cancel_at"]).tzinfo)

    def test_checkout_clears_a_stale_cancel_date(self) -> None:
        """A resubscribe must not show the old subscription's end date."""
        user = self.given_user(cancel_at=utc(PERIOD_END))
        payload = event_payload(
            "checkout.session.completed",
            checkout_session_object(str(self.row(user).id)),
            event_id="evt_me_resubscribe",
        )
        self.deliver(payload)
        body = self.client.get("/api/me", headers=self.headers(user)).json()
        self.assertEqual(body["plan"], PLAN_MONTHLY)
        self.assertIsNone(body["cancel_at"])

    def test_a_subscriber_cannot_open_checkout_twice(self) -> None:
        user = self.given_user()
        payload = event_payload(
            "checkout.session.completed",
            checkout_session_object(str(self.row(user).id)),
            event_id="evt_twice",
        )
        self.deliver(payload)
        response = self.client.post("/api/billing/checkout", headers=self.headers(user))
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
