# One image, one service: the built SPA and the API are served by the same
# process (see docs/deploy.md, Section 1). Built by Railway from the repo root.

# ---------------------------------------------------------------------------
# Build stage: the frontend bundle.
# ---------------------------------------------------------------------------
FROM node:22-slim AS frontend

# Vite inlines this at build time, so it is baked into the bundle and changing
# it means a rebuild, not a restart. Railway passes service variables to
# declared build args. It is a publishable key — public by design, not a secret.
ARG VITE_CLERK_PUBLISHABLE_KEY

# Fail here rather than three minutes later with a bundle that looks fine and
# cannot sign anyone in: an empty key is inlined as an empty string, so Clerk
# fails at runtime in the browser, not at build time.
RUN test -n "$VITE_CLERK_PUBLISHABLE_KEY" || { \
      echo "ERROR: build arg VITE_CLERK_PUBLISHABLE_KEY is empty." >&2; \
      echo "Vite inlines it at build time, so it must be set for the build," >&2; \
      echo "not just at runtime. Set it as a Railway service variable (Railway" >&2; \
      echo "passes service variables to declared build args), or pass" >&2; \
      echo "--build-arg VITE_CLERK_PUBLISHABLE_KEY=pk_test_... to docker build." >&2; \
      exit 1; \
    }

WORKDIR /build

# Manifests first: `npm ci` is re-run only when the dependencies change,
# not on every source edit.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Runtime stage: Python, Chromium, the backend, and that bundle.
# ---------------------------------------------------------------------------
# Pinned to the version the suite passes on (.venv-dev), and to a named Debian
# release: `--with-deps` below installs Chromium's system libraries by apt
# package name, so an unpinned `-slim` rolling to the next Debian could change
# or drop one of those packages and break the build with no change here.
FROM python:3.14-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Requirements before the source, for the same layer-caching reason as above.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Headless rendering uses Chromium's headless shell; --with-deps pulls the
# system libraries it needs. Installed as root into PLAYWRIGHT_BROWSERS_PATH,
# then made world-readable so the unprivileged user below can launch it.
RUN python -m playwright install --with-deps --only-shell chromium \
    && chmod -R a+rX /ms-playwright

# Only the backend and the bundle. No resources/, no probe.py, no venvs —
# see .dockerignore. The frontend lands at /app/frontend/dist so main.py's
# package-relative lookup (parents[2] / "frontend" / "dist") finds it.
COPY backend/ /app/backend/
COPY --from=frontend /build/dist /app/frontend/dist

# Nothing here needs to write to the image or run privileged.
RUN useradd --create-home --uid 10001 app
USER app

# alembic.ini and the app package are both resolved from here, so the
# pre-deploy `alembic upgrade head` in railway.toml works unchanged.
WORKDIR /app/backend

# sh -c so Railway's $PORT expands. Exactly one worker: the render limits in
# app/render_slots.py are in-process state.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
