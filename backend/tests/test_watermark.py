"""The PDF watermark, and `/api/render-pdf` as a security boundary.

`/api/render-pdf` takes HTML and CSS off the wire and runs them through headless
Chromium. Three things have to hold, and each is checked here against a real
render rather than against the template string:

* the endpoint needs a session — it is not an open rendering service;
* every page carries `Generated for <email>`, composed from that session and not
  from the request body;
* the page reaches no network, so neither an SSRF probe nor a slow external
  reference gets anywhere.

The endpoint tests need `TEST_DATABASE_URL` (they create and drop tables, so
they refuse to touch `DATABASE_URL`) and a Chromium installed for Playwright.
The pure-render tests need only Chromium.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import sqlalchemy as sa
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from sqlalchemy.orm import sessionmaker

from app import auth
from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import User
from app.pdf import _pad_to_even, render_pdf
from tests.fake_clerk import PUBLIC_KEY, make_token

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

#: A document that spans several pages, so "every page" means more than one.
MULTIPAGE_HTML = "".join(
    f"<section style='break-after:page'><h2>Question {n}</h2>"
    f"<p>Work out the value of x when 3x + {n} = {3 * n}.</p></section>"
    for n in range(1, 4)
)


def page_texts(pdf_bytes: bytes) -> list[str]:
    """The extracted text of each page, in order."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [page.extract_text() or "" for page in reader.pages]


class TestFooterText(unittest.TestCase):
    """What the footer says, and on which pages it says it."""

    def test_every_page_carries_the_account_email(self) -> None:
        pdf = render_pdf(MULTIPAGE_HTML, "", email="test@example.com")
        pages = page_texts(pdf)
        self.assertGreater(len(pages), 1, "expected a multi-page document")
        for index, text in enumerate(pages):
            self.assertIn(
                "Generated for test@example.com",
                text,
                f"page {index + 1} of {len(pages)} has no watermark",
            )

    def test_exact_footer_format(self) -> None:
        pdf = render_pdf("<p>x</p>", "", email="jane@example.com", on=dt.date(2026, 10, 5))
        self.assertIn(
            "Generated for jane@example.com · 5 Oct 2026", page_texts(pdf)[0]
        )

    def test_day_is_not_zero_padded(self) -> None:
        pdf = render_pdf("<p>x</p>", "", email="a@example.com", on=dt.date(2026, 1, 9))
        text = page_texts(pdf)[0]
        self.assertIn("· 9 Jan 2026", text)
        self.assertNotIn("09 Jan", text)

    def test_the_padding_page_is_watermarked_too(self) -> None:
        """An odd paper gains a blank page for double-sided printing.

        It leaves the building like any other page, so it is watermarked and
        numbered in sequence — which is why the pad is made inside Chromium
        rather than stitched on afterwards.
        """
        pdf = render_pdf(MULTIPAGE_HTML, "", email="pad@example.com")
        pages = page_texts(pdf)
        self.assertEqual(len(pages) % 2, 0, "papers print double-sided")
        self.assertNotIn("Question", pages[-1], "expected the last page to be the pad")
        self.assertIn("Generated for pad@example.com", pages[-1])

    def test_page_numeral_survives_alongside_the_watermark(self) -> None:
        """The watermark is a second line, not a replacement for the numeral."""
        pages = page_texts(render_pdf(MULTIPAGE_HTML, "", email="n@example.com"))
        for index, text in enumerate(pages):
            self.assertIn(str(index + 1), text, f"page {index + 1} lost its numeral")

    def test_html_in_the_email_is_escaped(self) -> None:
        """The address is interpolated into HTML Chromium parses; escape it."""
        pdf = render_pdf(
            "<p>x</p>", "", email="<b>a@example.com</b>", on=dt.date(2026, 10, 5)
        )
        self.assertIn("Generated for <b>a@example.com</b>", page_texts(pdf)[0])


def blank_pdf(pages: int) -> bytes:
    """A minimal A4 PDF of `pages` blank pages."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class TestPadToEven(unittest.TestCase):
    """The stitch-on-a-blank-page fallback, used when the in-document pad misses."""

    def test_an_even_pdf_passes_through_unchanged(self) -> None:
        """No page added, and the bytes are handed back untouched."""
        original = blank_pdf(4)
        result = _pad_to_even(original)
        self.assertEqual(result, original, "an even PDF was rewritten")
        self.assertEqual(len(PdfReader(io.BytesIO(result)).pages), 4)

    def test_an_odd_pdf_gains_one_page(self) -> None:
        """The companion case, so the guard cannot be inverted unnoticed."""
        result = _pad_to_even(blank_pdf(3))
        self.assertEqual(len(PdfReader(io.BytesIO(result)).pages), 4)


class TestNoNetworkDuringRender(unittest.TestCase):
    """The renderer must not fetch anything the request body points it at."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.hits: list[str] = []
        hits = cls.hits

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                hits.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()

            def log_message(self, *args: object) -> None:
                pass

        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.origin = "http://127.0.0.1:%d" % cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self) -> None:
        self.hits.clear()

    def test_external_references_are_never_fetched(self) -> None:
        html = (
            f'<h1>Report</h1><img src="{self.origin}/pixel.png">'
            f'<p>Body text.</p>'
        )
        css = f'@import url("{self.origin}/theme.css");'
        pdf = render_pdf(html, css, email="test@example.com")
        self.assertEqual(self.hits, [], "the render reached the network")
        self.assertIn("Report", page_texts(pdf)[0], "the document still renders")

    def test_an_unroutable_host_does_not_hang_the_render(self) -> None:
        """`wait_until='networkidle'` would otherwise sit on a dead reference."""
        html = (
            '<h1>Hostile</h1>'
            '<img src="http://10.255.255.1/hang.png">'
            '<script src="http://169.254.169.254/latest/meta-data"></script>'
            '<p>Still rendered.</p>'
        )
        started = time.monotonic()
        pdf = render_pdf(html, "", email="test@example.com")
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 30, f"render took {elapsed:.1f}s — it waited on the net")
        text = page_texts(pdf)[0]
        self.assertIn("Hostile", text)
        self.assertIn("Still rendered.", text)
        self.assertIn("Generated for test@example.com", text)

    def test_inline_data_uris_still_load(self) -> None:
        """Diagrams are inline, so blocking the net must not block them."""
        red_dot = (
            "data:image/gif;base64,"
            "R0lGODlhAQABAIABAP8AAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="
        )
        pdf = render_pdf(
            f'<p>Shape</p><img src="{red_dot}" style="width:40px;height:40px">',
            "",
            email="test@example.com",
        )
        self.assertIn("Shape", page_texts(pdf)[0])


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL to a throwaway Postgres to run these "
    "(they create and drop tables)",
)
class RenderEndpointTestCase(unittest.TestCase):
    """A test database, a client, and a patched Clerk signing key."""

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
        self._real_signing_key = auth.signing_key
        auth.signing_key = lambda token: PUBLIC_KEY
        os.environ["FREE_GENERATION_LIMIT"] = "1"
        os.environ["DAILY_GENERATION_LIMIT"] = "10"
        os.environ["AUTHORIZED_PARTIES"] = "http://localhost:5173"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        auth.signing_key = self._real_signing_key
        get_settings.cache_clear()

    def header(self, **kwargs) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(**kwargs)}"}


class TestRenderEndpointRequiresAuth(RenderEndpointTestCase):
    def test_no_header_is_401(self) -> None:
        response = self.client.post(
            "/api/render-pdf", json={"html": "<p>x</p>", "css": ""}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": {"code": "auth_required"}})

    def test_bad_token_is_401(self) -> None:
        response = self.client.post(
            "/api/render-pdf",
            json={"html": "<p>x</p>", "css": ""},
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        self.assertEqual(response.status_code, 401)

    def test_rendering_costs_no_generation(self) -> None:
        """Re-downloading a paper you already have is free."""
        headers = self.header(sub="user_free_dl", email="test@example.com")
        for _ in range(3):
            response = self.client.post(
                "/api/render-pdf",
                json={"html": "<p>x</p>", "css": ""},
                headers=headers,
            )
            self.assertEqual(response.status_code, 200)
        with self.Session() as s:
            user = s.query(User).one()
        self.assertEqual(user.total_generations, 0)


class TestGeneratedPaperIsWatermarked(RenderEndpointTestCase):
    """The done-when: a paper generated as a test user, every page stamped."""

    def test_every_page_of_a_generated_paper_names_the_account(self) -> None:
        headers = self.header(sub="user_paper_pdf", email="test@example.com")

        generated = self.client.post(
            "/api/generate-paper",
            json={
                "topics": ["percentages"],
                "target_marks": 30,
                "include_answers": True,
                "seed": 11,
            },
            headers=headers,
        )
        self.assertEqual(generated.status_code, 200)
        paper = generated.json()
        self.assertGreater(len(paper["questions"]), 0)

        # Stand in for the React document: the paper's own text, paginated.
        html = "".join(
            f"<section style='break-after:page'><h2>Question {n}</h2>"
            f"<p>{question['stem'] or ''}</p>"
            + "".join(f"<p>{part['prompt']}</p>" for part in question["parts"])
            + "</section>"
            for n, question in enumerate(paper["questions"][:6], start=1)
        )

        response = self.client.post(
            "/api/render-pdf",
            json={"html": html, "css": "body{font-family:sans-serif}"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")

        pages = page_texts(response.content)
        self.assertGreater(len(pages), 1)
        for index, text in enumerate(pages):
            self.assertIn(
                "Generated for test@example.com",
                text,
                f"page {index + 1} of {len(pages)} has no watermark",
            )

    def test_the_email_comes_from_the_session_not_the_body(self) -> None:
        """A forged address in the request body must be ignored."""
        headers = self.header(sub="user_forge", email="real@example.com")
        response = self.client.post(
            "/api/render-pdf",
            json={
                "html": "<p>x</p>",
                "css": "",
                "email": "victim@example.com",
                "footer_template": "<div>anything</div>",
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        text = page_texts(response.content)[0]
        self.assertIn("Generated for real@example.com", text)
        self.assertNotIn("victim@example.com", text)

    def test_two_accounts_get_their_own_watermark(self) -> None:
        for sub, email in (("user_one", "one@example.com"), ("user_two", "two@example.com")):
            response = self.client.post(
                "/api/render-pdf",
                json={"html": "<p>x</p>", "css": ""},
                headers=self.header(sub=sub, email=email),
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(f"Generated for {email}", page_texts(response.content)[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
