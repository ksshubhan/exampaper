"""The render subprocess: one PDF, then exit.

Reads a JSON job from stdin, writes the PDF to stdout, and says nothing else on
stdout — the parent treats those bytes as the document. A traceback goes to
stderr and a non-zero exit, which the parent turns into a `RenderError`.

It exists so a render can be *killed*. Headless Chromium prints HTML and CSS
that arrived over the wire, `page.pdf()` has no timeout of its own, and a
wedged renderer cannot be unwedged from inside the process that is waiting on
it. Run as `python app/render_worker.py`, started by `app.pdf.render_pdf`.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

# Started by path, not as a module, so `app` is not importable yet: the server
# may have been launched from anywhere. `backend/` is this file's grandparent.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pdf import render_document  # noqa: E402


def main() -> int:
    job = json.loads(sys.stdin.buffer.read())
    on = job.get("on")
    pdf = render_document(
        job["html"],
        job["css"],
        email=job["email"],
        on=dt.date.fromisoformat(on) if on else None,
    )
    sys.stdout.buffer.write(pdf)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
