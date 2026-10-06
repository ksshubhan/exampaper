"""Headless-Chromium PDF rendering.

The browser's own print dialog injects a header (page title + date) and footer
(URL + `Page N of M`) that CSS cannot remove. We render the paper's HTML through
headless Chromium instead, with `display_header_footer` under our control: an
empty header, and a footer carrying a bare page numeral in the bottom outer
corner — the Edexcel convention — above a centred watermark naming the account
the paper was generated for.

Two things here are a security boundary, not cosmetics. The HTML and CSS come
straight off the wire, so:

* the watermark is composed **here**, from the authenticated user's email. It is
  never read from the request body, so a caller cannot forge another account's
  name onto a paper, or leave the line off;
* the page gets **no network**. Every request whose scheme is not `data:` or
  `about:` is aborted, which keeps this from being an open proxy that fetches
  arbitrary URLs from our server, and stops a hostile external reference hanging
  the `networkidle` wait below. Diagrams are inline SVG and the stylesheet
  arrives in the request body, so a correct render needs nothing from the net.
"""

from __future__ import annotations

import datetime as dt
import io
from html import escape
from zoneinfo import ZoneInfo

from playwright.sync_api import Route, sync_playwright
from pypdf import PdfReader, PdfWriter

# The calendar day the footer dates a paper by — the same clock the generation
# limits run on, so "today" means one thing across the app.
LONDON = ZoneInfo("Europe/London")

# A4 with the Edexcel-ish margin. The bottom is deeper than the top to hold the
# two footer lines (numeral, then watermark) without either touching content.
_PAGE_MARGIN = {"top": "18mm", "bottom": "20mm", "left": "15mm", "right": "15mm"}

#: The only schemes that may load while a document prints. Both are
#: in-memory: nothing here can reach the network, the filesystem (`file:`) or
#: the cloud metadata service.
_ALLOWED_SCHEMES = ("data", "about")

_EMPTY_HEADER = "<span></span>"


def _footer_template(email: str, on: dt.date) -> str:
    """The per-page footer: page numeral bottom-right, watermark centred below.

    `email` is escaped — it reaches us from Clerk, and this string is HTML that
    Chromium parses.
    """
    stamp = f"Generated for {email} · {on.day} {on:%b} {on.year}"
    return (
        '<div style="width:100%;font-family:Arial,Helvetica,sans-serif;'
        'padding:0 15mm;box-sizing:border-box;">'
        '<div style="font-size:9px;color:#000;text-align:right;line-height:1.2;">'
        '<span class="pageNumber"></span>'
        "</div>"
        '<div style="font-size:8px;color:#8a8a8a;text-align:center;'
        'line-height:1.3;padding-top:1mm;">'
        f"{escape(stamp)}"
        "</div>"
        "</div>"
    )


def _block_network(route: Route) -> None:
    """Abort anything that would leave the machine; allow inline sources only."""
    scheme = route.request.url.split(":", 1)[0].strip().lower()
    if scheme in _ALLOWED_SCHEMES:
        route.continue_()
    else:
        route.abort()


def _page_count(pdf_bytes: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


#: Appended to force one more printed page. Done inside the document, rather
#: than by stitching a blank page on afterwards, so the padding page comes out
#: of Chromium like any other — watermarked, and numbered in sequence.
_PAD_PAGE = """() => {
    const pad = document.createElement('div');
    pad.style.breakBefore = 'page';
    pad.style.height = '1px';
    document.body.appendChild(pad);
}"""


def _pad_to_even(pdf_bytes: bytes) -> bytes:
    """Stitch on a blank page. The fallback if the in-document pad misses."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    last = reader.pages[-1].mediabox
    writer.add_blank_page(width=last.width, height=last.height)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def render_pdf(html: str, css: str, *, email: str, on: dt.date | None = None) -> bytes:
    """Render a self-contained HTML fragment + CSS to a clean, even-page A4 PDF.

    `email` is the authenticated account's address and goes into the footer of
    every page; it is a keyword argument so no call site can pass it by accident
    from somewhere untrusted. `on` defaults to today in Europe/London.
    """
    document = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head><body>{html}</body></html>"
    )
    footer = _footer_template(email, on or dt.datetime.now(LONDON).date())
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.route("**/*", _block_network)
            # Blocked requests surface as console/page errors, not exceptions;
            # the render carries on without them, which is the intent.
            page.set_content(document, wait_until="networkidle")

            def to_pdf() -> bytes:
                return page.pdf(
                    format="A4",
                    margin=_PAGE_MARGIN,
                    print_background=True,
                    display_header_footer=True,
                    header_template=_EMPTY_HEADER,
                    footer_template=footer,
                    prefer_css_page_size=False,
                )

            # Papers print double-sided, so the page count must be even. Pad in
            # the document and print again, which costs a second print pass but
            # keeps the extra page inside Chromium's footer machinery.
            pdf = to_pdf()
            if _page_count(pdf) % 2:
                page.evaluate(_PAD_PAGE)
                padded = to_pdf()
                pdf = padded if _page_count(padded) % 2 == 0 else _pad_to_even(pdf)
        finally:
            browser.close()
    return pdf
