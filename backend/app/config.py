"""Environment-backed settings.

Every value comes from the process environment. `backend/.env` is loaded first
if it exists, but a real environment variable always wins — `load_dotenv` does
not override what is already set. No secret is ever defaulted to a real value:
defaults here are development conveniences only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# backend/.env, i.e. one level up from this package.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_FRONTEND_URL = "http://localhost:5173"
DEFAULT_FREE_GENERATION_LIMIT = 1
DEFAULT_DAILY_GENERATION_LIMIT = 10
#: An abuse ceiling, not an allowance: it sits above the monthly plan's
#: fair-use cap of 10 so a paying customer never meets it in normal use.
DEFAULT_MAX_DAILY_ATTEMPTS = 20


def _csv_env(name: str) -> tuple[str, ...]:
    """A comma-separated env var as a tuple, blanks dropped."""
    raw = os.getenv(name) or ""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _int_env(name: str, default: int) -> int:
    """An int from the environment, falling back if unset or not a number."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Settings read once at import. Extend as later sections add env vars."""

    frontend_url: str
    # No default: there is no sane fallback for a database, and silently
    # pointing at the wrong one is worse than failing loudly.
    database_url: str | None
    # Clerk. Both are required to authenticate a request, but absence is
    # reported when a request arrives, not at import, so the app still boots.
    clerk_secret_key: str | None
    clerk_jwks_url: str | None
    #: Origins allowed in a session token's `azp` claim. Defaults to the one
    #: frontend we serve, so a token minted for somewhere else is rejected.
    authorized_parties: tuple[str, ...]
    # Stripe, test mode for now. Like the Clerk keys, a missing value is
    # reported when a request needs it rather than at import.
    stripe_secret_key: str | None
    stripe_webhook_secret: str | None
    stripe_price_monthly: str | None
    free_generation_limit: int
    daily_generation_limit: int
    #: Generation *attempts* allowed per Europe/London day, on every plan.
    #: One per reserved slot, counted before any work starts and never
    #: refunded — otherwise a loop of generate-then-disconnect is free. A
    #: refused request reserves nothing, so it costs nothing.
    max_daily_attempts: int


@lru_cache
def get_settings() -> Settings:
    """Cached settings. Call `get_settings.cache_clear()` in tests that patch env."""
    return Settings(
        frontend_url=os.getenv("FRONTEND_URL", DEFAULT_FRONTEND_URL),
        database_url=os.getenv("DATABASE_URL") or None,
        clerk_secret_key=os.getenv("CLERK_SECRET_KEY") or None,
        clerk_jwks_url=os.getenv("CLERK_JWKS_URL") or None,
        authorized_parties=_csv_env("AUTHORIZED_PARTIES")
        or (os.getenv("FRONTEND_URL", DEFAULT_FRONTEND_URL),),
        stripe_secret_key=os.getenv("STRIPE_SECRET_KEY") or None,
        stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET") or None,
        stripe_price_monthly=os.getenv("STRIPE_PRICE_MONTHLY") or None,
        free_generation_limit=_int_env(
            "FREE_GENERATION_LIMIT", DEFAULT_FREE_GENERATION_LIMIT
        ),
        daily_generation_limit=_int_env(
            "DAILY_GENERATION_LIMIT", DEFAULT_DAILY_GENERATION_LIMIT
        ),
        max_daily_attempts=_int_env(
            "MAX_DAILY_ATTEMPTS", DEFAULT_MAX_DAILY_ATTEMPTS
        ),
    )
