"""ExamPaper API.

Every route lives on one `/api`-prefixed router, so a path is spelled the same
by the browser, by the Vite dev proxy (which forwards `/api` without rewriting
it) and by anything calling the backend directly — a Stripe CLI webhook forward,
say, which never passes through Vite at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .assembler import build_paper
from .auth import get_current_user
from .config import get_settings
from .generators.registry import topics_catalog
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
def generate_paper(
    req: GeneratePaperRequest,
    user: User = Depends(get_current_user),
) -> Paper:
    """Assemble a full custom paper from the chosen topics.

    Authenticated, but not yet rate-limited — Section 4 reserves a generation
    slot here.
    """
    return build_paper(req)


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
