"""Clerk session-JWT authentication.

A request proves who it is with `Authorization: Bearer <clerk session jwt>`.
The token is verified against Clerk's published JWKS — signature, `exp` and
`nbf` — and its `sub` claim is mapped onto a row in `users`, created the first
time we see that user.

Every failure path returns the same 401 body, `{"detail": {"code":
"auth_required"}}`: a caller learns that it must authenticate, not which part
of its token we disliked.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

#: Clerk's Backend API, used only to look up an email the token didn't carry.
CLERK_API_BASE = "https://api.clerk.com/v1"
_CLERK_TIMEOUT = httpx.Timeout(10.0)

AUTH_REQUIRED_DETAIL = {"code": "auth_required"}


def auth_required() -> HTTPException:
    """The single 401 every auth failure raises."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AUTH_REQUIRED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def bearer_token(authorization: str | None) -> str:
    """The token out of an `Authorization: Bearer <token>` header."""
    if not authorization:
        raise auth_required()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise auth_required()
    return token.strip()


@lru_cache
def _jwk_client() -> PyJWKClient:
    """Cached JWKS client. Refetches when it meets an unknown key id."""
    url = get_settings().clerk_jwks_url
    if not url:
        raise auth_required()
    return PyJWKClient(url, cache_keys=True)


def signing_key(token: str) -> Any:
    """Public key Clerk signed this token with. Patched in tests."""
    return _jwk_client().get_signing_key_from_jwt(token).key


def verify_session_token(token: str) -> dict[str, Any]:
    """Decode and verify a Clerk session token, or raise 401.

    Audience is not checked: a Clerk session token's `aud` is not a value we
    issue, and the spec asks for signature, `exp` and `nbf` only.
    """
    try:
        return jwt.decode(
            token,
            signing_key(token),
            algorithms=["RS256"],
            options={
                "require": ["exp", "sub"],
                "verify_exp": True,
                "verify_nbf": True,
                "verify_aud": False,
                "verify_signature": True,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:  # invalid signature, expired, malformed, unknown kid
        raise auth_required() from exc


def email_from_claims(claims: dict[str, Any]) -> str | None:
    """An email address out of the token, if Clerk was configured to include one."""
    for key in ("email", "email_address", "primary_email_address"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def fetch_email_from_clerk(clerk_user_id: str) -> str:
    """Ask Clerk for a user's primary email. Used when the token omits it."""
    secret = get_settings().clerk_secret_key
    if not secret:
        raise auth_required()
    try:
        response = httpx.get(
            f"{CLERK_API_BASE}/users/{clerk_user_id}",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=_CLERK_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise auth_required() from exc

    addresses = payload.get("email_addresses") or []
    primary_id = payload.get("primary_email_address_id")
    for address in addresses:
        if address.get("id") == primary_id and address.get("email_address"):
            return str(address["email_address"])
    for address in addresses:
        if address.get("email_address"):
            return str(address["email_address"])
    raise auth_required()


def get_or_create_user(
    db: Session, clerk_user_id: str, email: str | None
) -> User:
    """The row for this Clerk user, created on first sight."""
    existing = db.execute(
        select(User).where(User.clerk_user_id == clerk_user_id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    user = User(
        clerk_user_id=clerk_user_id,
        email=email or fetch_email_from_clerk(clerk_user_id),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two first requests raced; the other one won. Take its row.
        db.rollback()
        return db.execute(
            select(User).where(User.clerk_user_id == clerk_user_id)
        ).scalar_one()
    db.refresh(user)
    return user


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: the authenticated account holder, or 401."""
    claims = verify_session_token(bearer_token(authorization))
    clerk_user_id = claims.get("sub")
    if not isinstance(clerk_user_id, str) or not clerk_user_id.strip():
        raise auth_required()
    return get_or_create_user(db, clerk_user_id.strip(), email_from_claims(claims))
