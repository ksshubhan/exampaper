"""Clerk authentication, against a mocked JWKS.

Tokens come from `tests.fake_clerk`, which signs them with an in-process RSA key
and lets us patch `app.auth.signing_key` to the matching public half. The real
`jwt.decode` path still runs; only the key lookup is faked.

Needs `TEST_DATABASE_URL`: these tests create and drop tables, so they refuse
to touch `DATABASE_URL`.
"""

from __future__ import annotations

import os
import unittest
from datetime import timedelta

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import auth
from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import User
from tests.fake_clerk import OTHER_PRIVATE_KEY, PUBLIC_KEY, make_token

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL to a throwaway Postgres to run these "
    "(they create and drop tables)",
)
class AuthTestCase(unittest.TestCase):
    """Shared harness: a test database, a client, and a patched signing key."""

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

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()

    def setUp(self) -> None:
        with self.Session() as s:
            s.query(User).delete()
            s.commit()
        # Stand in for Clerk's JWKS endpoint.
        self._real_signing_key = auth.signing_key
        auth.signing_key = lambda token: PUBLIC_KEY
        # Known limits, independent of whatever backend/.env says.
        os.environ["FREE_GENERATION_LIMIT"] = "1"
        os.environ["DAILY_GENERATION_LIMIT"] = "10"
        os.environ["AUTHORIZED_PARTIES"] = "http://localhost:5173,https://exampaper.test"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        auth.signing_key = self._real_signing_key
        get_settings.cache_clear()

    def users(self) -> list[User]:
        with self.Session() as s:
            return list(s.query(User).order_by(User.created_at))

    def auth_header(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}


class TestMissingOrMalformedHeader(AuthTestCase):
    def test_no_header_is_401_auth_required(self) -> None:
        response = self.client.get("/api/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": {"code": "auth_required"}})

    def test_www_authenticate_header_present(self) -> None:
        response = self.client.get("/api/me")
        self.assertEqual(response.headers.get("www-authenticate"), "Bearer")

    def test_wrong_scheme_is_401(self) -> None:
        response = self.client.get(
            "/api/me", headers={"Authorization": "Basic abc123"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "auth_required")

    def test_bearer_with_no_token_is_401(self) -> None:
        response = self.client.get("/api/me", headers={"Authorization": "Bearer "})
        self.assertEqual(response.status_code, 401)

    def test_no_user_row_is_created_by_a_rejected_request(self) -> None:
        self.client.get("/api/me")
        self.assertEqual(self.users(), [])


class TestBadToken(AuthTestCase):
    def test_garbage_token_is_401(self) -> None:
        response = self.client.get("/api/me", headers=self.auth_header("not-a-jwt"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "auth_required")

    def test_signature_from_another_key_is_401(self) -> None:
        token = make_token(key=OTHER_PRIVATE_KEY)
        response = self.client.get("/api/me", headers=self.auth_header(token))
        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_401(self) -> None:
        token = make_token(expires_in=timedelta(minutes=-5))
        response = self.client.get("/api/me", headers=self.auth_header(token))
        self.assertEqual(response.status_code, 401)

    def test_not_yet_valid_token_is_401(self) -> None:
        token = make_token(not_before=timedelta(minutes=10))
        response = self.client.get("/api/me", headers=self.auth_header(token))
        self.assertEqual(response.status_code, 401)

    def test_token_without_exp_is_401(self) -> None:
        token = make_token(omit=("exp",))
        response = self.client.get("/api/me", headers=self.auth_header(token))
        self.assertEqual(response.status_code, 401)

    def test_token_without_sub_is_401(self) -> None:
        token = make_token(omit=("sub",))
        response = self.client.get("/api/me", headers=self.auth_header(token))
        self.assertEqual(response.status_code, 401)

    def test_bad_tokens_create_no_rows(self) -> None:
        for token in ("not-a-jwt", make_token(key=OTHER_PRIVATE_KEY)):
            self.client.get("/api/me", headers=self.auth_header(token))
        self.assertEqual(self.users(), [])


class TestValidToken(AuthTestCase):
    def test_creates_the_user_on_first_sight(self) -> None:
        token = make_token(sub="user_first", email="first@example.com")
        response = self.client.get("/api/me", headers=self.auth_header(token))
        self.assertEqual(response.status_code, 200)

        rows = self.users()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].clerk_user_id, "user_first")
        self.assertEqual(rows[0].email, "first@example.com")
        self.assertEqual(rows[0].plan, "free")

    def test_second_call_reuses_the_same_row(self) -> None:
        token = make_token(sub="user_again", email="again@example.com")
        first = self.client.get("/api/me", headers=self.auth_header(token))
        second = self.client.get("/api/me", headers=self.auth_header(token))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

        rows = self.users()
        self.assertEqual(len(rows), 1, "a second request must not create a row")
        self.assertEqual(first.json(), second.json())

    def test_a_fresh_token_for_the_same_user_reuses_the_row(self) -> None:
        """Signing in again issues a new token but must not duplicate the user."""
        for _ in range(3):
            token = make_token(sub="user_same", email="same@example.com")
            self.assertEqual(
                self.client.get("/api/me", headers=self.auth_header(token)).status_code,
                200,
            )
        self.assertEqual(len(self.users()), 1)

    def test_distinct_subs_get_distinct_rows(self) -> None:
        for name in ("user_a", "user_b"):
            token = make_token(sub=name, email=f"{name}@example.com")
            self.client.get("/api/me", headers=self.auth_header(token))
        self.assertEqual({u.clerk_user_id for u in self.users()}, {"user_a", "user_b"})

    def test_me_payload_shape(self) -> None:
        token = make_token(sub="user_shape", email="shape@example.com")
        body = self.client.get("/api/me", headers=self.auth_header(token)).json()
        self.assertEqual(
            set(body),
            {
                "email",
                "plan",
                "cancel_at",
                "total_generations",
                "day_generations",
                "free_limit",
                "daily_limit",
            },
        )
        self.assertEqual(body["email"], "shape@example.com")
        self.assertEqual(body["plan"], "free")
        self.assertIsNone(body["cancel_at"])
        self.assertEqual(body["total_generations"], 0)
        self.assertEqual(body["day_generations"], 0)
        self.assertEqual(body["free_limit"], 1)
        self.assertEqual(body["daily_limit"], 10)

    def test_limits_follow_the_environment(self) -> None:
        os.environ["FREE_GENERATION_LIMIT"] = "3"
        os.environ["DAILY_GENERATION_LIMIT"] = "25"
        get_settings.cache_clear()
        token = make_token(sub="user_limits", email="limits@example.com")
        body = self.client.get("/api/me", headers=self.auth_header(token)).json()
        self.assertEqual((body["free_limit"], body["daily_limit"]), (3, 25))


class TestAuthorizedParty(AuthTestCase):
    """`azp` must name an origin we serve, when the token carries one."""

    def test_token_with_no_azp_is_accepted(self) -> None:
        token = make_token(sub="user_noazp", email="noazp@example.com")
        response = self.client.get("/api/me", headers=self.auth_header(token))
        self.assertEqual(response.status_code, 200)

    def test_matching_azp_is_accepted(self) -> None:
        token = make_token(
            sub="user_goodazp", email="good@example.com", azp="http://localhost:5173"
        )
        response = self.client.get("/api/me", headers=self.auth_header(token))
        self.assertEqual(response.status_code, 200)

    def test_second_authorized_party_is_accepted(self) -> None:
        token = make_token(
            sub="user_azp2", email="azp2@example.com", azp="https://exampaper.test"
        )
        self.assertEqual(
            self.client.get("/api/me", headers=self.auth_header(token)).status_code, 200
        )

    def test_foreign_azp_is_rejected(self) -> None:
        token = make_token(
            sub="user_badazp", email="bad@example.com", azp="https://evil.example"
        )
        response = self.client.get("/api/me", headers=self.auth_header(token))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "auth_required")
        self.assertEqual(self.users(), [], "a rejected token must create no row")

    def test_authorized_parties_defaults_to_frontend_url(self) -> None:
        del os.environ["AUTHORIZED_PARTIES"]
        os.environ["FRONTEND_URL"] = "https://only-this.example"
        get_settings.cache_clear()
        try:
            good = make_token(
                sub="user_dflt_ok", email="a@example.com", azp="https://only-this.example"
            )
            bad = make_token(
                sub="user_dflt_no", email="b@example.com", azp="http://localhost:5173"
            )
            self.assertEqual(
                self.client.get("/api/me", headers=self.auth_header(good)).status_code,
                200,
            )
            self.assertEqual(
                self.client.get("/api/me", headers=self.auth_header(bad)).status_code,
                401,
            )
        finally:
            os.environ.pop("FRONTEND_URL", None)
            get_settings.cache_clear()


class TestRemovedEndpoint(AuthTestCase):
    def test_single_question_endpoint_is_gone(self) -> None:
        response = self.client.post(
            "/api/generate",
            json={
                "format": "past-papers",
                "qualification": "gcse",
                "board": "edexcel",
                "subject": "maths",
            },
        )
        self.assertEqual(response.status_code, 404)


class TestMisconfiguration(AuthTestCase):
    """A missing Clerk setting is a 401, never a 500."""

    def test_unset_jwks_url_is_401(self) -> None:
        auth.signing_key = self._real_signing_key  # use the real JWKS path
        auth._jwk_client.cache_clear()
        previous = os.environ.pop("CLERK_JWKS_URL", None)
        get_settings.cache_clear()
        try:
            token = make_token(sub="user_misconf", email="m@example.com")
            response = self.client.get("/api/me", headers=self.auth_header(token))
        finally:
            if previous is not None:
                os.environ["CLERK_JWKS_URL"] = previous
            auth._jwk_client.cache_clear()
            get_settings.cache_clear()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "auth_required")
        self.assertEqual(self.users(), [])

    def test_unset_jwks_url_logs_an_error_naming_the_variable(self) -> None:
        auth.signing_key = self._real_signing_key
        auth._jwk_client.cache_clear()
        previous = os.environ.pop("CLERK_JWKS_URL", None)
        get_settings.cache_clear()
        try:
            token = make_token(sub="user_logjwks", email="l@example.com")
            with self.assertLogs("app.auth", level="ERROR") as captured:
                self.client.get("/api/me", headers=self.auth_header(token))
        finally:
            if previous is not None:
                os.environ["CLERK_JWKS_URL"] = previous
            auth._jwk_client.cache_clear()
            get_settings.cache_clear()
        self.assertTrue(
            any("CLERK_JWKS_URL" in line for line in captured.output),
            f"expected CLERK_JWKS_URL in the log, got {captured.output}",
        )

    def test_unset_secret_key_logs_an_error_naming_the_variable(self) -> None:
        """Reached only when the token has no email, so Clerk must be consulted."""
        previous = os.environ.pop("CLERK_SECRET_KEY", None)
        get_settings.cache_clear()
        try:
            token = make_token(sub="user_logsecret", email=None)
            with self.assertLogs("app.auth", level="ERROR") as captured:
                response = self.client.get("/api/me", headers=self.auth_header(token))
        finally:
            if previous is not None:
                os.environ["CLERK_SECRET_KEY"] = previous
            get_settings.cache_clear()
        self.assertEqual(response.status_code, 401)
        self.assertTrue(
            any("CLERK_SECRET_KEY" in line for line in captured.output),
            f"expected CLERK_SECRET_KEY in the log, got {captured.output}",
        )
        self.assertEqual(self.users(), [])


class TestEmailFallback(AuthTestCase):
    """When the token carries no email, Clerk's API supplies it."""

    def test_email_fetched_from_clerk_when_absent_from_token(self) -> None:
        calls: list[str] = []

        def fake_fetch(clerk_user_id: str) -> str:
            calls.append(clerk_user_id)
            return "fetched@example.com"

        real = auth.fetch_email_from_clerk
        auth.fetch_email_from_clerk = fake_fetch
        try:
            token = make_token(sub="user_noemail", email=None)
            response = self.client.get("/api/me", headers=self.auth_header(token))
        finally:
            auth.fetch_email_from_clerk = real

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["user_noemail"])
        self.assertEqual(response.json()["email"], "fetched@example.com")

    def test_clerk_is_not_called_when_the_token_has_an_email(self) -> None:
        def explode(clerk_user_id: str) -> str:
            raise AssertionError("Clerk must not be called when the token has an email")

        real = auth.fetch_email_from_clerk
        auth.fetch_email_from_clerk = explode
        try:
            token = make_token(sub="user_hasemail", email="has@example.com")
            response = self.client.get("/api/me", headers=self.auth_header(token))
        finally:
            auth.fetch_email_from_clerk = real
        self.assertEqual(response.status_code, 200)


class TestProtectedEndpoints(AuthTestCase):
    """Generation and PDF rendering now require a user."""

    PAPER_BODY = {
        "topics": ["percentages"],
        "target_marks": 20,
        "include_answers": True,
        "seed": 7,
    }
    PDF_BODY = {"html": "<p>x</p>", "css": "", "filename": "paper.pdf"}

    def test_generate_paper_requires_auth(self) -> None:
        response = self.client.post("/api/generate-paper", json=self.PAPER_BODY)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "auth_required")

    def test_render_pdf_requires_auth(self) -> None:
        response = self.client.post("/api/render-pdf", json=self.PDF_BODY)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "auth_required")

    def test_generate_paper_succeeds_with_a_valid_token(self) -> None:
        token = make_token(sub="user_paper", email="paper@example.com")
        response = self.client.post(
            "/api/generate-paper", json=self.PAPER_BODY, headers=self.auth_header(token)
        )
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.json()["questions"]), 0)

    def test_public_endpoints_stay_public(self) -> None:
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/api/topics").status_code, 200)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
