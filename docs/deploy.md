# Deploy — build spec

Save as `docs/deploy.md` in the ExamPaper repo. Same workflow as
`docs/accounts-and-payments.md`: **one section per prompt**, `/clear` between
sections, commit after each section passes its done-when. Sections marked
**(me)** are dashboard work for Sshubhan, not Claude Code.

Kickoff prompt for Claude Code sections (1 and 2 only):

> Read `docs/deploy.md`. Do Section N only. Stop when its done-when passes and tell me the result.

This spec is how the `## Deploy checklist` in `docs/accounts-and-payments.md`
gets done. Every checklist item maps to a section here (table at the end).

---

## Decisions (closed)

- **App host:** Railway, Hobby plan, region **EU West (Amsterdam)**. One service,
  built from a `Dockerfile` at the repo root, deployed from GitHub
  (`ksshubhan/ExamPaper`, `main`).
- **Database:** Neon free plan, region **AWS Europe (London) `aws-eu-west-2`**.
  Not Railway Postgres.
- **One service serves everything.** FastAPI serves the built frontend
  (`frontend/dist`) as well as `/api`. Same origin, so the frontend's relative
  `/api/...` calls work unchanged and CORS stays a safety net.
- **Exactly one uvicorn worker, one replica.** The render limits are in-process
  (`app/render_slots.py`).
- **Python 3.14 in the image** — the version the suite passes on (`.venv-dev`).
- **Rollout in three stages**, each one usable on its own:
  1. Section 4 — Railway URL, **Clerk development keys + Stripe test mode**.
     This meets the definition of done ("deployed at a URL").
  2. Section 5 — `exampaper.sshubhan.com` + **Clerk production instance**.
  3. Section 6 — **Stripe live mode**. Gated; see that section.
- **Migrations run as Railway's pre-deploy command** (`alembic upgrade head`),
  so a failed migration stops the deploy and the previous one keeps serving.
- **No config file in the repo.** Railway has deprecated config files, and
  `railway.toml` is ignored for this service, so the pre-deploy command and the
  healthcheck are **set in the Railway UI** — dashboard state, not code. They
  are recorded in Section 3 (set) and Section 4 (confirmed in the deploy log).
  The one thing this costs: those two settings are not in version control, so
  recreating the service means setting them again from Section 3.

## Fences (all sections)

- Do not touch `probe.py`, `.venv`, `.venv-dev`, or anything in `resources/`.
- Never run `git checkout .`, `git reset --hard`, or `git stash`.
- Do not change question generation, sympy verification, blueprint logic,
  diagram code, auth, billing, limits, or the render pipeline. The only
  `backend/app` change in this spec is the static-file serving in Section 1
  (plus the one conditional line in Section 4, only if its trigger happens).
- No secrets in code or in the Dockerfile. Everything comes from Railway
  service variables.
- No new paid services beyond Railway (Hobby) and Neon (free).
- **No `ANTHROPIC_API_KEY` anywhere in the deploy.** Nothing deployed calls a model.
- `resources/` (copyrighted exam material) must never enter the image:
  exclude it in `.dockerignore` as well as `.gitignore`.

## Env vars

**No new env vars.** Production sets every variable in `backend/.env.example`
(except `TEST_DATABASE_URL`, which stays unset) plus `VITE_CLERK_PUBLISHABLE_KEY`,
which the frontend build reads at **build time** — the Dockerfile declares it
as an `ARG`, and Railway passes service variables to declared build args.
Changing it means a rebuild, not a restart.

---

## Section 1 — Serve the frontend from FastAPI

Goal: one process serves the SPA and the API, so production has one origin.

- In `backend/app/main.py`, **after** `app.include_router(api)`, serve the built
  frontend from `frontend/dist`, resolved relative to the package
  (`Path(__file__).resolve().parents[2] / "frontend" / "dist"`), not the cwd.
- **Only if that directory exists.** With no build present (tests, a fresh
  clone, the dev server) nothing is mounted and behaviour is unchanged.
- Behaviour, exactly:
  - `GET /api/...` is never answered by the frontend. An unknown `/api` path is
    FastAPI's normal JSON 404, not `index.html`.
  - `GET /assets/<file>` serves the hashed bundle with
    `Cache-Control: public, max-age=31536000, immutable`.
  - Any other `GET` that names a real file in `dist` (favicon, anything from
    `frontend/public`) serves that file.
  - Any other `GET` — `/`, `/account`, `/pricing`,
    `/practice/gcse/edexcel/maths/paper`, a typo — serves `index.html` with
    `Cache-Control: no-cache`, so React Router handles it and a redeploy is
    picked up on the next load.
  - Paths are resolved and checked to stay inside `dist`. `GET /../backend/.env`
    and URL-encoded variants must not escape it.
- Do not change the Vite dev setup. In dev, `npm run dev` on 5173 stays the way
  to work; port 8000 serving a stale `dist` is harmless.

Done when: `pytest` passes, including a new `tests/test_static.py` that points
the server at a temporary `dist` (an `index.html`, one `assets/app.js`, one
`favicon.svg`) and asserts: `/` and `/account` return the index with
`no-cache`; `/assets/app.js` returns the file with the `immutable` header;
`/favicon.svg` returns the file; `/api/nope` is a JSON 404; `/api/health` is
still `{"status": "ok"}`; a traversal attempt is a 404; and with no `dist`
directory, `/` is a 404 (nothing mounted).

---

## Section 2 — The container image

Goal: one image that builds the frontend, installs the backend and Chromium,
and runs one worker. Railway's own deploy settings are not here — they are
dashboard work in Section 3.

- **`Dockerfile`** at the repo root, two stages:
  - **Build stage**, `node:22-slim`: `ARG VITE_CLERK_PUBLISHABLE_KEY`, copy
    `frontend/package.json` + `package-lock.json`, `npm ci`, copy the rest of
    `frontend/`, `npm run build`.
  - **Runtime stage**, `python:3.14-slim`:
    - `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`,
      `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`.
    - `pip install --no-cache-dir -r backend/requirements.txt`, then
      `python -m playwright install --with-deps --only-shell chromium`.
      (Headless rendering uses Chromium's headless shell; `--with-deps` pulls
      the system libraries it needs.)
    - Copy **only** `backend/` (to `/app/backend`) and the build stage's
      `frontend/dist` (to `/app/frontend/dist`), so Section 1's relative path
      resolves. `WORKDIR /app/backend`.
    - Run as a non-root user, with `/ms-playwright` readable by it.
    - `CMD` via `sh -c` so `$PORT` expands:
      `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1`.
- **`.dockerignore`**: `.git`, `.venv`, `.venv-dev`, `**/node_modules`,
  `frontend/dist`, `**/__pycache__`, `**/.env`, `**/.env.*` (keep
  `!**/.env.example`), `resources/`, `probe.py`, `.claude/`, `.DS_Store`.
- **No `railway.toml`.** Railway has deprecated config files and ignores one
  for this service. The pre-deploy command and the healthcheck are set in the
  UI instead — Section 3, step 4. A Dockerfile at the repo root is detected
  without any config, so nothing is lost on the build side.
  - Because that file is where a comment about it would have gone: one replica
    and one worker is not a default to leave alone but a correctness
    requirement — the concurrent-render limit is in-process state in
    `app/render_slots.py`, so a second worker or replica hands out the same
    slots twice. The `--workers 1` in the `CMD` is half of it; one replica (the
    Railway default, left alone) is the other. Scaling out needs that state in
    Postgres first — see the deploy checklist in
    `docs/accounts-and-payments.md`.

Done when, **if Docker is installed locally**:
```
docker build --build-arg VITE_CLERK_PUBLISHABLE_KEY=<pk_test_…> -t exampaper .
docker run --rm -p 8000:8000 --env-file backend/.env \
  -e DATABASE_URL=postgresql+psycopg://<user>:<pass>@host.docker.internal:5432/exampaper \
  -e FRONTEND_URL=http://localhost:8000 exampaper
```
then at `http://localhost:8000`: sign in, generate a paper, download the PDF,
open it, watermark present. Also `docker run --rm exampaper ls /app` shows only
`backend` and `frontend`, and the image contains no `resources`.
**If Docker is not installed**: done when the two files (`Dockerfile`,
`.dockerignore`) exist and `pytest` still passes; the Railway build in
Section 4 is the build check.

---

## Section 3 — Neon and Railway accounts (me)

1. **Neon**: create a project in **AWS Europe (London)**. Copy the **direct**
   (not `-pooler`) connection string. Change the scheme to
   `postgresql+psycopg://` and keep the query string (`sslmode=require` …).
   That is `DATABASE_URL`.
2. **Railway**: sign up with GitHub, subscribe to **Hobby**. Under workspace
   usage, set a **hard usage limit** (e.g. $10) so a bug or abuse can never run
   up a bill.
3. New project → Deploy from GitHub repo → `ksshubhan/ExamPaper`. In the
   service settings: region **EU West**, serverless/app sleeping **off**
   (Chromium cold starts are slow, and webhooks must land). Networking →
   **Generate Domain** → note the `*.up.railway.app` URL.
4. **Deploy settings, in the UI** (service → Settings → Deploy). These replace
   the deprecated `railway.toml`, so they exist only here:
   - **Pre-deploy command**: `alembic upgrade head`. This is what makes a
     failed migration stop the deploy while the previous image keeps serving.
     It runs with the image's working directory (`/app/backend`), where
     `alembic.ini` sits, so the bare command is correct.
   - **Healthcheck path**: `/api/health`, timeout **120** seconds. The timeout
     is generous on purpose: a cold start installs nothing but does import the
     app and open a connection to a Neon instance that may have scaled to zero.
   - **Restart policy**: on failure (Railway's default — nothing to change).
   - Leave replicas at **1**. See Section 2 for why that is a requirement and
     not a default worth revisiting.

Done when: the Railway service exists in EU West with a generated domain; its
Deploy settings show the pre-deploy command and the `/api/health` healthcheck;
and Neon shows an empty database in London.

---

## Section 4 — First public deploy, test mode (me)

1. **Stripe (test mode)** → Developers → Webhooks → add endpoint
   `https://<railway-domain>/api/stripe/webhook` with events
   `checkout.session.completed`, `customer.subscription.updated`,
   `customer.subscription.deleted`. Copy its signing secret (**not** the
   `stripe listen` one).
2. **Railway service variables** — every name in `backend/.env.example`:
   - Clerk **development** keys, the same as local: `CLERK_SECRET_KEY`,
     `CLERK_JWKS_URL`, `VITE_CLERK_PUBLISHABLE_KEY`.
   - Stripe test: `STRIPE_SECRET_KEY` (`sk_test_…`), `STRIPE_PRICE_MONTHLY`,
     `STRIPE_WEBHOOK_SECRET` from step 1.
   - `FRONTEND_URL=https://<railway-domain>` (no trailing slash).
     `AUTHORIZED_PARTIES` left blank (defaults to `FRONTEND_URL`).
   - `DATABASE_URL` from Section 3.
   - The limits **set explicitly**, not left to defaults:
     `FREE_GENERATION_LIMIT=1`, `DAILY_GENERATION_LIMIT=10`,
     `MAX_DAILY_ATTEMPTS=20`, `MAX_DAILY_RENDERS=50`,
     `RENDER_TIMEOUT_SECONDS=20`, `MAX_CONCURRENT_RENDERS=2`,
     `RENDER_SLOT_WAIT_SECONDS=10`.
   - Not set: `ANTHROPIC_API_KEY`, `TEST_DATABASE_URL`.
3. Deploy. The deploy log shows `alembic upgrade head` applying
   `0001_initial`, `0002_attempt_cap` and `0003_render_cap`, then a passing
   healthcheck. Both come from the UI settings in Section 3, step 4 — there is
   no config file to fall back on, so if the log shows no migration step or no
   healthcheck, the setting did not save rather than the deploy being fine.
4. **Stripe Customer Portal (test mode)**: add the Railway domain wherever the
   portal settings ask for your site/return URLs.

**If the PDF download fails** and the deploy logs show Chromium crashing with
`/dev/shm` or "Target crashed" errors: one Claude Code prompt — in
`render_document` in `backend/app/pdf.py`, launch with
`args=["--disable-dev-shm-usage"]`. That is the only permitted render change.
Nothing else in the render pipeline changes for this spec.

Done when, **on the public Railway URL, in a fresh private window**:
`/api/health` is ok; `/account` reloads without a 404; sign in with Google;
generate one paper; download the PDF and **open it** (questions, diagrams,
watermark with your email and today's date); generate again → upgrade popup →
pay with `4242 4242 4242 4242` → `/account` shows Unlimited; Manage
subscription → cancel → plan back to Free. Stripe's webhook page shows 200s.
In Railway metrics, memory during a render stays well under the service limit.

**Stop point.** At this point the definition of done is met. Sections 5 and 6
make it a real product, not a requirement for "deployed at a URL".

---

## Section 5 — Custom domain + Clerk production (me)

Clerk production needs a domain you own; `*.up.railway.app` will not work.
DNS can take up to 48 h, so start this as soon as Section 4 passes.

1. **Railway** → service → Networking → Custom domain
   `exampaper.sshubhan.com`. Add the CNAME it shows at sshubhan.com's DNS
   provider. Wait for Railway to show the certificate as issued.
2. **Clerk** → create the **production instance** for
   `exampaper.sshubhan.com`. Add every DNS record its Domains page lists.
   Wait until they verify, then deploy certificates.
3. **Google OAuth** (production can't use Clerk's shared credentials): Google
   Cloud Console → OAuth consent screen (External, app name ExamPaper,
   **publish it** — left in "Testing", only listed test users can sign in) →
   create a Web OAuth client with the redirect URI Clerk shows → paste the
   client ID and secret into Clerk's Google connection. Enable email magic link
   in production too.
4. **Railway variables**: `CLERK_SECRET_KEY` (`sk_live_…`), `CLERK_JWKS_URL`
   (the production one), `VITE_CLERK_PUBLISHABLE_KEY` (`pk_live_…`),
   `FRONTEND_URL=https://exampaper.sshubhan.com`. Redeploy (the publishable
   key is baked in at build).
5. **Stripe (still test mode)**: edit the webhook endpoint URL to
   `https://exampaper.sshubhan.com/api/stripe/webhook` (same secret), and
   update the portal's site URLs.

Done when: the Section 4 run-through passes again on
`https://exampaper.sshubhan.com`, with no Clerk "development mode" badge, and
a sign-in from a Google account you have never used here works.

---

## Section 6 — Stripe live mode (me) — gated

**Do not start until** `docs/before-launch.md` Sections 4–5
(end-of-period cancellation + `Cancels on {date}` on `/account`) are built.
Live customers must keep what they paid for until the period ends.

1. Activate the Stripe account (business details, bank account).
2. In **live mode**: create product "ExamPaper Unlimited" + monthly price;
   turn on the Customer Portal with **cancel at end of period** + update
   payment method; add the webhook endpoint
   `https://exampaper.sshubhan.com/api/stripe/webhook` with the same three
   events.
3. **Railway variables**: `STRIPE_SECRET_KEY` (`sk_live_…`),
   `STRIPE_PRICE_MONTHLY` (live price), `STRIPE_WEBHOOK_SECRET` (live
   endpoint's secret). Redeploy.

Done when: one real subscription with your own card → `/account` shows
Unlimited → cancel in the portal → plan stays Unlimited and shows the cancel
date → refund yourself in the Stripe dashboard.

---

## Deploy checklist → section

| `accounts-and-payments.md` checklist item | Where |
|---|---|
| One uvicorn worker | Section 2 (`--workers 1`, one replica) |
| `MAX_CONCURRENT_RENDERS` from memory | Section 4 (set explicitly, checked in metrics) |
| Migrate the production database | Section 3 (pre-deploy command, in the UI), Section 4 (log check) |
| Pin one Python version | Section 2 (`python:3.14-slim-trixie`) |
| No `ANTHROPIC_API_KEY` | Fences, Section 4 |
| Live Stripe keys + production webhook | Section 6 |
| Clerk production instance | Section 5 |
| Every env var set | Section 4 |
| Chromium on the host + one real PDF opened | Section 2 (image), Section 4 (done-when) |

## Known limits (not work)

- **Neon free compute**: 100 CU-hours a month, scale-to-zero after 5 idle
  minutes (first query after that is a little slower). Fine at launch traffic.
  If Neon ever reports the limit reached, move to its Launch plan (pay as you go).
- **Railway Hobby** includes $5 of usage; memory is billed on what is used, so
  an idle API costs little and Chromium is only paid for while it renders.

## Not in this spec (→ later.md)

- Everything already in `docs/later.md`.
- More than one worker or replica (needs the render state moved to Postgres first).
