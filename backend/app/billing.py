"""Stripe: hosted Checkout, the Customer Portal, and one webhook.

Test mode only for now — nothing here cares which mode the keys are for, but
`docs/accounts-and-payments.md` does.

**Access is granted by the webhook, never by the success redirect.** A browser
coming back to `/account?upgraded=1` proves nothing: anyone can type that URL.
Only a signed event from Stripe moves a row to `plan='monthly'`.

Every call into Stripe goes through a thin module-level function —
`create_checkout_session`, `create_portal_session`, `construct_event` — so the
tests can replace the network without reaching into the SDK.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .auth import get_current_user
from .config import get_settings
from .db import get_db
from .models import PLAN_FREE, PLAN_MONTHLY, StripeEvent, User

logger = logging.getLogger(__name__)

router = APIRouter()

#: Subscription statuses that entitle an account to the monthly plan. Anything
#: else — `past_due`, `unpaid`, `incomplete`, `canceled` — drops back to free.
ENTITLING_STATUSES = frozenset({"active", "trialing"})

#: The status we write when Checkout completes. The subscription events that
#: follow carry Stripe's own wording and overwrite it.
STATUS_ACTIVE = "active"
STATUS_CANCELED = "canceled"

#: `checkout.session.completed` `payment_status` values that mean the money is
#: settled. A session can complete with `unpaid` — asynchronous payment methods
#: finish the session now and settle (or fail) minutes later — and completing is
#: not paying.
PAID_STATUSES = frozenset({"paid", "no_payment_required"})

ALREADY_SUBSCRIBED_DETAIL = {"code": "already_subscribed"}
NO_CUSTOMER_DETAIL = {"code": "no_customer"}
#: One code for "we cannot talk to Stripe right now", whether that is a missing
#: key (an operator must fix it) or Stripe being down (try again later). The
#: frontend shows the same thing either way; the log says which it was.
BILLING_UNAVAILABLE_DETAIL = {"code": "billing_unavailable"}


def billing_unavailable(reason: str) -> HTTPException:
    """503, with the cause in the log rather than in the response."""
    logger.error("Billing is unavailable: %s", reason)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=BILLING_UNAVAILABLE_DETAIL,
    )


def bad_signature(reason: str) -> HTTPException:
    """400 for anything we could not verify came from Stripe."""
    logger.warning("Rejected a webhook delivery: %s", reason)
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_signature"}
    )


def configure_stripe() -> None:
    """Point the SDK at our account, or refuse the request."""
    key = get_settings().stripe_secret_key
    if not key:
        raise billing_unavailable(
            "STRIPE_SECRET_KEY is not set. Set it in backend/.env "
            "(see backend/.env.example)."
        )
    stripe.api_key = key


# --- the seams tests replace -------------------------------------------------


def create_checkout_session(**params: Any) -> Any:
    configure_stripe()
    return stripe.checkout.Session.create(**params)


def create_portal_session(**params: Any) -> Any:
    configure_stripe()
    return stripe.billing_portal.Session.create(**params)


def construct_event(payload: bytes, signature: str | None) -> dict[str, Any]:
    """Verify a delivery against `STRIPE_WEBHOOK_SECRET` and parse it.

    The payload is the **raw** request body: the signature covers those exact
    bytes, so anything re-serialised would fail to verify even when the JSON is
    equivalent.

    Verification is the SDK's, but the parsing is plain `json`:
    `construct_event` would hand back a `StripeObject`, which in stripe-python
    8+ is deliberately not a dict — the handlers below are much plainer with
    real dicts, and the tests can then build an event without the SDK at all.

    `tolerance` is passed explicitly because `verify_header` skips the timestamp
    check entirely when it is left at `None`, and that check is what stops a
    captured delivery being replayed tomorrow.
    """
    secret = get_settings().stripe_webhook_secret
    if not secret:
        # Without the secret we cannot tell Stripe from anyone else, so we
        # believe nobody. Loud, because it looks like Stripe going silent.
        logger.error(
            "STRIPE_WEBHOOK_SECRET is not set — rejecting every webhook "
            "delivery. `stripe listen` prints the signing secret to use in "
            "backend/.env."
        )
        raise bad_signature("STRIPE_WEBHOOK_SECRET is not set")
    if not signature:
        raise bad_signature("no Stripe-Signature header")

    try:
        stripe.WebhookSignature.verify_header(
            payload, signature, secret, tolerance=stripe.Webhook.DEFAULT_TOLERANCE
        )
    except Exception as exc:  # bad signature, or a timestamp outside tolerance
        raise bad_signature(f"{type(exc).__name__}: {exc}") from exc

    try:
        event = json.loads(payload)
    except ValueError as exc:
        raise bad_signature(f"body is not JSON: {exc}") from exc
    if not isinstance(event, dict) or not isinstance(event.get("id"), str):
        raise bad_signature("body is not a Stripe event")
    return event


# --- endpoints ---------------------------------------------------------------


@router.post("/billing/checkout")
def checkout(user: User = Depends(get_current_user)) -> dict[str, str]:
    """A hosted Checkout URL for the monthly plan."""
    if user.plan == PLAN_MONTHLY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ALREADY_SUBSCRIBED_DETAIL
        )

    settings = get_settings()
    if not settings.stripe_price_monthly:
        raise billing_unavailable("STRIPE_PRICE_MONTHLY is not set")

    params: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": settings.stripe_price_monthly, "quantity": 1}],
        # How the webhook finds this user again. Stripe hands it straight back.
        "client_reference_id": str(user.id),
        "success_url": f"{settings.frontend_url}/account?upgraded=1",
        "cancel_url": f"{settings.frontend_url}/pricing",
    }
    # Reuse the customer if we have one, so a resubscribe lands on the same
    # Stripe customer instead of creating a duplicate.
    if user.stripe_customer_id:
        params["customer"] = user.stripe_customer_id
    else:
        params["customer_email"] = user.email

    try:
        session = create_checkout_session(**params)
    except stripe.StripeError as exc:
        raise billing_unavailable(f"Stripe refused to open Checkout: {exc}") from exc
    return {"url": session.url}


@router.post("/billing/portal")
def portal(user: User = Depends(get_current_user)) -> dict[str, str]:
    """A Customer Portal URL, where a subscriber cancels or updates their card."""
    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=NO_CUSTOMER_DETAIL
        )

    settings = get_settings()
    try:
        session = create_portal_session(
            customer=user.stripe_customer_id,
            return_url=f"{settings.frontend_url}/account",
        )
    except stripe.StripeError as exc:
        raise billing_unavailable(f"Stripe refused to open the portal: {exc}") from exc
    return {"url": session.url}


# --- webhook ----------------------------------------------------------------


def object_id(value: Any) -> str | None:
    """An id out of a field Stripe sends either as an id or as an object."""
    if isinstance(value, dict):
        value = value.get("id")
    return str(value) if isinstance(value, str) and value.strip() else None


def user_by_reference(db: Session, reference: Any) -> User | None:
    """The user a `client_reference_id` points at, if it points at one."""
    if not isinstance(reference, str) or not reference.strip():
        return None
    try:
        user_id = uuid.UUID(reference.strip())
    except ValueError:
        return None
    return db.get(User, user_id)


def user_by_subscription(db: Session, subscription_id: str | None) -> User | None:
    if not subscription_id:
        return None
    return db.execute(
        select(User).where(User.stripe_subscription_id == subscription_id)
    ).scalar_one_or_none()


def handle_checkout_completed(db: Session, obj: dict[str, Any]) -> None:
    """Checkout finished — which is not the same as paid for.

    Grants the plan only when `payment_status` says the money is settled.
    Otherwise it records the Stripe ids and stops: those ids are what lets
    `customer.subscription.updated` find this user, and that event grants access
    the moment the subscription turns `active`. An unrecognised or missing
    `payment_status` is treated as unpaid — the subscription event will still
    arrive, so being cautious here costs a few seconds, while guessing wrong
    gives away the product.
    """
    reference = obj.get("client_reference_id")
    user = user_by_reference(db, reference)
    if user is None:
        # A `stripe trigger` fixture, or a session opened by something that is
        # not us. Nothing to grant, and no reason to make Stripe retry.
        logger.warning(
            "checkout.session.completed: no user for client_reference_id=%r", reference
        )
        return

    customer_id = object_id(obj.get("customer"))
    subscription_id = object_id(obj.get("subscription"))
    if customer_id:
        user.stripe_customer_id = customer_id
    if subscription_id:
        user.stripe_subscription_id = subscription_id

    payment_status = obj.get("payment_status")
    if payment_status not in PAID_STATUSES:
        logger.info(
            "checkout.session.completed for %s with payment_status=%r: keeping "
            "the ids, holding the plan at %r until the subscription is active.",
            user.email,
            payment_status,
            user.plan,
        )
        return

    user.plan = PLAN_MONTHLY
    user.subscription_status = STATUS_ACTIVE
    logger.info("Granted the monthly plan to %s", user.email)


def handle_subscription_updated(db: Session, obj: dict[str, Any]) -> None:
    """Status changed: entitlement follows it, in both directions."""
    subscription_id = object_id(obj.get("id"))
    user = user_by_subscription(db, subscription_id)
    if user is None:
        logger.warning(
            "customer.subscription.updated: no user for subscription %r",
            subscription_id,
        )
        return

    new_status = obj.get("status")
    user.subscription_status = new_status if isinstance(new_status, str) else None
    user.plan = PLAN_MONTHLY if new_status in ENTITLING_STATUSES else PLAN_FREE


def handle_subscription_deleted(db: Session, obj: dict[str, Any]) -> None:
    """Subscription gone: back to free."""
    subscription_id = object_id(obj.get("id"))
    user = user_by_subscription(db, subscription_id)
    if user is None:
        logger.warning(
            "customer.subscription.deleted: no user for subscription %r",
            subscription_id,
        )
        return

    user.plan = PLAN_FREE
    user.subscription_status = STATUS_CANCELED


#: Event types we act on. Everything else is acknowledged and dropped.
HANDLERS: dict[str, Callable[[Session, dict[str, Any]], None]] = {
    "checkout.session.completed": handle_checkout_completed,
    "customer.subscription.updated": handle_subscription_updated,
    "customer.subscription.deleted": handle_subscription_deleted,
}


def claim_event(db: Session, event_id: str) -> bool:
    """Record an event id, or report that we have already seen it.

    `ON CONFLICT DO NOTHING` rather than select-then-insert: Stripe retries, and
    two deliveries of the same event can be in flight at once. The loser of that
    race blocks on the row until the winner commits, then sees zero rows.

    Deliberately *not* committed here. The id and whatever the handler changes
    land in one transaction, so a handler that raises leaves no record of the
    event and the retry gets a fresh attempt.
    """
    inserted = db.execute(
        pg_insert(StripeEvent)
        .values(id=event_id)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(StripeEvent.id)
    ).scalar_one_or_none()
    return inserted is not None


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Stripe's side of the conversation. No auth: the signature is the auth."""
    event = construct_event(
        await request.body(), request.headers.get("stripe-signature")
    )
    event_id = str(event["id"])
    event_type = str(event.get("type") or "")

    if not claim_event(db, event_id):
        db.rollback()
        logger.info("Ignored a repeat delivery of %s (%s)", event_type, event_id)
        return {"status": "duplicate"}

    handler = HANDLERS.get(event_type)
    if handler is None:
        # Acknowledged, and the id is kept: we have decided this type is a no-op,
        # so a retry of it should stay a no-op.
        db.commit()
        return {"status": "ignored"}

    obj = (event.get("data") or {}).get("object") or {}
    handler(db, obj)
    db.commit()
    return {"status": "handled"}
