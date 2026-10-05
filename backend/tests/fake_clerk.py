"""A stand-in for Clerk, so auth can be exercised without the network.

An RSA keypair is generated in-process and tokens are signed with the private
half; a test patches `app.auth.signing_key` to hand back the public half. The
real `jwt.decode` path still runs — signature, `exp`, `nbf`, required claims —
only the key lookup is faked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()
#: A key Clerk never published, for "someone else signed this" tests.
OTHER_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(
    *,
    sub: str = "user_test123",
    email: str | None = "test@example.com",
    expires_in: timedelta = timedelta(minutes=30),
    not_before: timedelta | None = None,
    key: rsa.RSAPrivateKey | None = None,
    omit: tuple[str, ...] = (),
    azp: str | None = None,
) -> str:
    """A Clerk-shaped session JWT. `omit` drops claims to test what we require."""
    now = datetime.now(tz=timezone.utc)
    claims: dict = {
        "sub": sub,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_in).timestamp()),
    }
    if email is not None:
        claims["email"] = email
    if not_before is not None:
        claims["nbf"] = int((now + not_before).timestamp())
    if azp is not None:
        claims["azp"] = azp
    for name in omit:
        claims.pop(name, None)
    return jwt.encode(claims, key or PRIVATE_KEY, algorithm="RS256")


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
