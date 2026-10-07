"""ExamPaper API.

Every route lives on one `/api`-prefixed router, so a path is spelled the same
by the browser, by the Vite dev proxy (which forwards `/api` without rewriting
it) and by anything calling the backend directly — a Stripe CLI webhook forward,
say, which never passes through Vite at all.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .assembler import build_paper
from .auth import get_current_user
from .billing import router as billing_router
from .config import get_settings
from .generators.registry import topics_catalog
from .limits import (
    RenderCount,
    Reservation,
    count_render,
    pending_reservation,
    reserve_generation,
)
from .models import User
from .pdf import RenderTimeout, render_pdf
from .render_guard import MAX_RENDER_BODY_BYTES, TOO_LARGE_DETAIL, RenderBodyLimit
from .render_slots import BUSY_DETAIL, RenderBusy, hold_render_slot, render_slot
from .schema import GeneratePaperRequest, Paper

app = FastAPI(title="ExamPaper API", version="0.0.1")

#: The route whose body is capped, spelled once. The middleware matches on the
#: full path, so it has to be the prefixed one the server actually serves.
RENDER_PATH = "/api/render-pdf"

RENDER_TIMEOUT_DETAIL = {"code": "render_timeout"}

# Outermost, so an oversized render body is refused on its headers — before
# routing, before the JSON is decoded, before a session is looked up. Added
# before CORS only in source order; middleware added later runs first, so CORS
# still wraps this and a rejected request keeps its CORS headers.
app.add_middleware(RenderBodyLimit, path=RENDER_PATH)

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


# `hold_render_slot` is declared here, not as a parameter, so it resolves
# ahead of `count_render`: an account that already has a render in flight is
# turned away before it spends one.
@api.post("/render-pdf", dependencies=[Depends(hold_render_slot)])
async def render_pdf_endpoint(
    req: RenderPdfRequest,
    user: User = Depends(get_current_user),
    render: RenderCount = Depends(count_render),
) -> Response:
    """Print a paper (or mark scheme) to a clean, chrome-free A4 PDF.

    The client renders the document to HTML and hands us its CSS; we run it
    through headless Chromium so no browser-injected header/footer appears.

    Auth is required but no generation slot is taken: re-downloading a paper
    already generated is free. The watermark footer is stamped with the signed-in
    account's email, read from the session and never from `req` — the body is
    attacker-controlled, so a caller must not be able to name someone else or
    leave the footer off.

    Free is not unlimited, though: every call launches a Chromium, so
    `count_render` spends one of the day's renders first — and keeps it,
    because the launch is the cost whether or not a PDF comes out. The body
    was size-checked before it was parsed (see `render_guard`), the account is
    allowed one render at a time and the box a handful (see `render_slots`),
    and the render itself runs under a wall-clock budget; overrunning it is a
    504, not a worker pinned forever.
    """
    # A backstop, not the guard: the middleware already refused anything this
    # large without parsing it, which is the check that protects memory. This
    # one only covers the route being reached some other way — mounted without
    # the middleware, or called directly — and answers with the same code.
    if len(req.html) + len(req.css) > MAX_RENDER_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=TOO_LARGE_DETAIL,
        )

    try:
        # The slot is held around the threadpool hop only: queueing is not the
        # document being slow, so it is not charged to the render's budget.
        async with render_slot():
            pdf = await run_in_threadpool(
                render_pdf, req.html, req.css, email=user.email
            )
    except RenderBusy as exc:
        # Nothing was launched, so this is the one refusal that gives the
        # render back. Safe against a loop: one in-flight render per account.
        render.refund()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BUSY_DETAIL,
        ) from exc
    except RenderTimeout as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=RENDER_TIMEOUT_DETAIL,
        ) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{req.filename}"'},
    )


# Checkout, the Customer Portal and the Stripe webhook, mounted on the same
# `/api` prefix: `/api/billing/checkout`, `/api/billing/portal`,
# `/api/stripe/webhook`.
api.include_router(billing_router)

app.include_router(api)


# --- the built frontend ----------------------------------------------------- #
#
# In production one process serves both the SPA and the API, so there is one
# origin and the frontend's relative `/api/...` calls need no base URL. In
# development there is no build to serve: `npm run dev` on 5173 proxies `/api`
# here, and nothing below is mounted.

#: Where `npm run build` puts the bundle, resolved from this package rather
#: than the cwd — the container's working directory is `/app/backend`, and a
#: dev shell could be anywhere.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

#: Hashed filenames, so the bytes behind one can never change: cache forever.
IMMUTABLE = "public, max-age=31536000, immutable"

#: `index.html` is *not* hashed, so it must be revalidated every load —
#: otherwise a redeploy's new asset hashes are never asked for.
NO_CACHE = "no-cache"

#: Spelled out because Starlette gives a GET-only route a 405 on every other
#: verb. `OPTIONS` is listed for completeness; CORS answers preflights before
#: routing ever gets here.
SPA_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def _inside(dist: Path, relative: str) -> Path | None:
    """`relative` resolved under `dist`, or None if it escapes.

    The path arrives from the URL, already percent-decoded by Starlette, so
    `..`, `%2e%2e%2f` and an absolute `/etc/passwd` all reach here as ordinary
    path text. Resolving first and then checking containment covers all three
    at once, symlinks included — string-matching for `..` would not.
    """
    candidate = (dist / relative).resolve()
    if candidate != dist and dist not in candidate.parents:
        return None
    return candidate


def mount_frontend(target: FastAPI, dist: Path) -> bool:
    """Serve the SPA in `dist` from `target`, if that build exists.

    Returns whether anything was mounted, and must be called *after* the API
    router: the catch-all below would otherwise shadow every real route.
    """
    if not dist.is_dir():
        return False
    dist = dist.resolve()
    index = dist / "index.html"

    # Every method, not just GET: a catch-all that matched the path but not
    # the method would turn each unknown-path 404 into a 405 — Starlette
    # answers a path-only match that way — so `POST /api/mistyped` would stop
    # reporting that the endpoint does not exist. Anything but a read is 404ed
    # below instead.
    @target.api_route("/{spa_path:path}", methods=SPA_METHODS, include_in_schema=False)
    def spa(spa_path: str, request: Request) -> Response:
        # `/api` is the API's, always. Falling through to `index.html` would
        # answer a mistyped endpoint with 200 and a page of HTML, which is far
        # harder to debug than a 404 — and would hand a fetch() parse error
        # instead of the JSON the frontend knows how to read.
        if spa_path == "api" or spa_path.startswith("api/"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        # There is nothing here to write to, and no route that accepts one:
        # a non-read on an unmatched path is a path that does not exist.
        if request.method not in ("GET", "HEAD"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        resolved = _inside(dist, spa_path) if spa_path else None

        # Hashed bundle: cacheable forever, and a miss is a 404 rather than
        # the index, because a build never asks for an asset that isn't there.
        if spa_path.startswith("assets/"):
            if resolved is None or not resolved.is_file():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            return FileResponse(resolved, headers={"Cache-Control": IMMUTABLE})

        # Anything else that names a real file — favicon, robots.txt, whatever
        # was dropped in `frontend/public`.
        if resolved is not None and resolved.is_file():
            return FileResponse(resolved, headers={"Cache-Control": NO_CACHE})

        # Every other GET is a client-side route: `/`, `/account`, a deep
        # practice URL, or a typo. React Router decides which.
        if not index.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(index, headers={"Cache-Control": NO_CACHE})

    return True


mount_frontend(app, FRONTEND_DIST)
