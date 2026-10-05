"""ExamPaper API.

Every route lives on one `/api`-prefixed router, so a path is spelled the same
by the browser, by the Vite dev proxy (which forwards `/api` without rewriting
it) and by anything calling the backend directly — a Stripe CLI webhook forward,
say, which never passes through Vite at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .assembler import build_paper
from .auth import get_current_user
from .config import get_settings
from .generators.registry import topics_catalog
from .limits import Reservation, pending_reservation, reserve_generation
from .models import User
from .pdf import render_pdf
from .schema import GeneratePaperRequest, Paper

app = FastAPI(title="ExamPaper API", version="0.0.1")

# The Vite dev server proxies /api -> here, so same-origin in practice. CORS is
# a safety net for direct calls; the allowed origin follows FRONTEND_URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_url],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def refund_on_invalid_request(
    request: Request, exc: RequestValidationError
) -> Response:
    """A 422 must not cost a generation.

    FastAPI resolves dependencies before it validates the request body, so a
    malformed body reaches us with a slot already reserved. The reservation
    parks itself on `request.state`; give it back, then answer exactly as
    FastAPI would have.
    """
    reservation = pending_reservation(request)
    if reservation is not None:
        reservation.refund()
    return await request_validation_exception_handler(request, exc)


api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    """The signed-in account: who they are, their plan, and their allowances."""
    settings = get_settings()
    return {
        "email": user.email,
        "plan": user.plan,
        "total_generations": user.total_generations,
        "day_generations": user.day_generations,
        "free_limit": settings.free_generation_limit,
        "daily_limit": settings.daily_generation_limit,
    }


@api.get("/topics")
def topics() -> list[dict]:
    """Pickable topics grouped by strand, each with an archetype count."""
    return topics_catalog()


@api.post("/generate-paper", response_model=Paper)
async def generate_paper(
    req: GeneratePaperRequest,
    request: Request,
    reservation: Reservation = Depends(reserve_generation),
) -> Paper:
    """Assemble a full custom paper from the chosen topics.

    The generation slot is taken before any work starts — that is what makes the
    limit race-proof — and given back on *any* exit without a paper, so neither
    a bug in the assembler nor a browser tab closed halfway through costs
    someone their one free paper. Downloading the result is a separate call
    (`/render-pdf`) and costs nothing.

    `async def` plus an explicit threadpool hop, rather than a plain `def`: it
    puts the `await`, and so any cancellation of this request, inside our own
    `try`. A sync route is cancelled one frame up, inside FastAPI, where nothing
    we write can see it and the slot is already spent.
    """
    delivered = False
    try:
        paper = await run_in_threadpool(build_paper, req)
        # Uvicorn does not cancel a request whose client has gone: the paper is
        # assembled and the response is then thrown away. So ask, rather than
        # charging for a paper nobody can read.
        delivered = not await request.is_disconnected()
        return paper
    finally:
        if not delivered:
            # `finally`, not `except Exception`: a cancellation — which other
            # servers do raise on disconnect, and which arrives on shutdown —
            # is a CancelledError, i.e. a BaseException. The refund is a plain
            # blocking call on purpose: awaiting anything inside an
            # already-cancelled task raises at once and would skip it.
            reservation.refund()


class RenderPdfRequest(BaseModel):
    """A rendered HTML document + its stylesheet, to be printed to PDF."""

    html: str
    css: str
    filename: str = "paper.pdf"


@api.post("/render-pdf")
async def render_pdf_endpoint(
    req: RenderPdfRequest,
    user: User = Depends(get_current_user),
) -> Response:
    """Print a paper (or mark scheme) to a clean, chrome-free A4 PDF.

    The client renders the document to HTML and hands us its CSS; we run it
    through headless Chromium so no browser-injected header/footer appears.
    """
    pdf = await run_in_threadpool(render_pdf, req.html, req.css)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{req.filename}"'},
    )


app.include_router(api)
