"""One process, two jobs: the SPA and the API on the same origin.

In production there is no Vite dev server and no second host, so FastAPI serves
`frontend/dist` itself. That makes the catch-all route the last thing standing
between a URL and `index.html`, and three things have to stay true about it:

* `/api/...` is never answered with HTML. A mistyped endpoint has to come back
  as the JSON 404 the frontend can read, not a 200 page that fails to parse.
* The hashed bundle is immutable and the index is not, so a redeploy is picked
  up on the next load instead of after a cache expiry nobody controls.
* No URL — `..`, percent-encoded, or absolute — can reach a file outside
  `dist`. `backend/.env` sits two directories up from it.

Each test mounts a throwaway `dist` onto a fresh app carrying the real `/api`
router, rather than onto the imported `app`: mounting a catch-all is permanent,
and the rest of the suite shares that module-level instance.

No database and no Chromium: these are file reads.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import IMMUTABLE, NO_CACHE, api, mount_frontend

INDEX_HTML = "<!doctype html><title>ExamPaper</title><div id=root></div>"
APP_JS = "console.log('bundle')"
FAVICON = "<svg xmlns='http://www.w3.org/2000/svg'/>"


def write_dist(root: Path) -> Path:
    """The three kinds of file a real build produces, and nothing else."""
    dist = root / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML)
    (dist / "assets" / "app.js").write_text(APP_JS)
    (dist / "favicon.svg").write_text(FAVICON)
    return dist


def raw_get(app: FastAPI, target: str) -> int:
    """The status of a GET whose path goes on the wire *verbatim*.

    `TestClient` runs the URL through httpx, which applies RFC 3986
    `remove_dot_segments` before sending — so `/../backend/.env` leaves as
    `/backend/.env` and the server never sees a traversal at all. An attacker
    writes the bytes by hand and no such tidying happens, so testing through
    httpx would prove the client safe rather than the server.

    This drives the ASGI app directly with the scope uvicorn would build:
    `path` percent-decoded (`h11_impl.py` calls `unquote`), dot segments left
    exactly where they were.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": unquote(target),
        "raw_path": target.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"]


def build_app(dist: Path) -> tuple[FastAPI, bool]:
    """A fresh app with the real API router, then `dist` mounted after it."""
    app = FastAPI()
    app.include_router(api)
    return app, mount_frontend(app, dist)


class TestWithBuild(unittest.TestCase):
    """A `dist` is present — production, and the container image."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # A real repo layout, so `backend/.env` exists to try to escape to.
        root = Path(self._tmp.name)
        (root / "backend").mkdir()
        (root / "backend" / ".env").write_text("CLERK_SECRET_KEY=sk_test_secret")
        dist = write_dist(root)
        self.app, mounted = build_app(dist)
        self.assertTrue(mounted, "a dist directory must mount")
        self.client = TestClient(self.app)

    def test_root_is_the_index_revalidated(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, INDEX_HTML)
        self.assertEqual(r.headers["cache-control"], NO_CACHE)

    def test_client_routes_are_the_index(self):
        """React Router owns these paths; the server must not 404 them."""
        for path in (
            "/account",
            "/pricing",
            "/practice/gcse/edexcel/maths/paper",
            "/not-a-page-at-all",
        ):
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.text, INDEX_HTML)
                self.assertEqual(r.headers["cache-control"], NO_CACHE)

    def test_bundle_is_immutable(self):
        r = self.client.get("/assets/app.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, APP_JS)
        self.assertEqual(r.headers["cache-control"], IMMUTABLE)

    def test_missing_asset_is_a_404_not_the_index(self):
        """A build never requests an asset that isn't there, so this is a bug
        to surface — serving HTML from a `<script src>` only hides it."""
        r = self.client.get("/assets/does-not-exist.js")
        self.assertEqual(r.status_code, 404)

    def test_public_file_is_served(self):
        r = self.client.get("/favicon.svg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, FAVICON)

    def test_api_health_still_answers(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})

    def test_unknown_api_path_is_a_json_404(self):
        r = self.client.get("/api/nope")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"detail": "Not Found"})
        self.assertIn("application/json", r.headers["content-type"])

    def test_bare_api_prefix_is_a_json_404(self):
        r = self.client.get("/api")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"detail": "Not Found"})

    def test_unknown_post_is_still_a_404_not_a_405(self):
        """The catch-all must not turn "no such endpoint" into "wrong method".

        A GET-only catch-all matches the *path* of `POST /api/generate` and
        Starlette answers a path-only match with 405, so a removed or mistyped
        endpoint would stop reporting that it does not exist.
        """
        for method, path in (
            ("post", "/api/generate"),
            ("post", "/api/nope"),
            ("delete", "/api/me"),
            ("post", "/account"),
        ):
            with self.subTest(method=method, path=path):
                r = getattr(self.client, method)(path)
                self.assertEqual(r.status_code, 404)
                self.assertEqual(r.json(), {"detail": "Not Found"})

    def test_traversal_is_a_404(self):
        """Every spelling of "two directories up" is refused.

        `backend/.env` sits two levels above `dist` and holds the Clerk and
        Stripe secrets. A rejected path is a 404 and not the index: handing
        `index.html` back with a 200 would report a probe as a working page,
        and the client router has no route it could possibly mean.

        Driven through `raw_get`, because httpx normalises half of these away
        before they reach the app — see its docstring.
        """
        for target in (
            "/../backend/.env",
            "/..%2fbackend%2f.env",
            "/%2e%2e%2fbackend%2f.env",
            "/assets/../../backend/.env",
            "/assets/..%2f..%2fbackend%2f.env",
            "/../../etc/passwd",
            "//etc/passwd",
        ):
            with self.subTest(target=target):
                self.assertEqual(raw_get(self.app, target), 404)

    def test_raw_get_agrees_with_the_client_on_ordinary_paths(self):
        """`raw_get` must not be a different server from the one shipped.

        It bypasses httpx, so it is worth pinning that the paths it shares
        with the real client get the same answer — otherwise a 404 above
        could be an artefact of a malformed scope.
        """
        for target, expected in (
            ("/", 200),
            ("/account", 200),
            ("/assets/app.js", 200),
            ("/favicon.svg", 200),
            ("/api/health", 200),
            ("/api/nope", 404),
            ("/assets/does-not-exist.js", 404),
        ):
            with self.subTest(target=target):
                self.assertEqual(raw_get(self.app, target), expected)
                self.assertEqual(self.client.get(target).status_code, expected)

class TestWithoutBuild(unittest.TestCase):
    """No `dist` — the dev server, a fresh clone, and the test suite itself."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        missing = Path(self._tmp.name) / "frontend" / "dist"
        self.app, self.mounted = build_app(missing)
        self.client = TestClient(self.app)

    def test_nothing_is_mounted(self):
        self.assertFalse(self.mounted)

    def test_root_is_a_404(self):
        self.assertEqual(self.client.get("/").status_code, 404)

    def test_api_is_unaffected(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
