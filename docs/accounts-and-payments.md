# Accounts and payments — build spec

Save as `docs/accounts-and-payments.md` in the ExamPaper repo. Work through it **one section per prompt**, `/clear` between sections, commit after each section passes its done-when.

Kickoff prompt for each section:

> Read `docs/accounts-and-payments.md`. Do Section N only. Stop when its done-when passes and tell me the result.

---

## Decisions (closed)

- **Auth:** Clerk. Sign-in methods: Google + email magic link. No passwords.
- **Payments:** Stripe hosted Checkout + Stripe Customer Portal + one webhook. **Test mode only** for this whole spec.
- **Plans:** exactly two.
  - `free` — 1 generation total (paper OR worksheet), mark scheme included.
  - `monthly` — unlimited, with a fair-use cap of 10 generations per day (Europe/London calendar day).
- **Account holder is the parent.** No student accounts.
- Sign-in is required **at the moment of pressing Generate**, not to browse or pick topics.
- Limits are enforced **on the backend only**. The frontend just reacts to the 402.
- Access is granted **by the webhook**, never by the success redirect.
- Every generated PDF carries a watermark footer with the account email and date.

## Fences (all sections)

- Do not touch `probe.py` or `.venv`.
- Do not change question generation, sympy verification, blueprint logic, or diagram code.
- Only change `PaperPreview.tsx` / its stylesheet in Section 7, and only to add the footer.
- No secrets in code. All keys come from env vars listed below.
- No new paid services beyond Clerk and Stripe.

## Env vars (exact names)

Backend `.env`:
```
CLERK_SECRET_KEY=
CLERK_JWKS_URL=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_MONTHLY=
FRONTEND_URL=http://localhost:5173
FREE_GENERATION_LIMIT=1
DAILY_GENERATION_LIMIT=10
DATABASE_URL=
```
Frontend `.env`:
```
VITE_CLERK_PUBLISHABLE_KEY=
```
Add both to `.env.example` with empty values. Make sure `.env` is in `.gitignore`.

## Before you start (me, not Claude Code)

1. Create a Clerk application, enable Google + email magic link, copy the keys and JWKS URL.
2. In Stripe **test mode**: create product "ExamPaper Unlimited", recurring monthly price → copy the price ID into `STRIPE_PRICE_MONTHLY`.
3. Turn on the Customer Portal in Stripe test-mode settings (allow cancel + update payment method).
4. Install the Stripe CLI, run `stripe login`.

---

## Section 0 — Audit (no code)

Goal: report what exists so later sections fit the real layout.

Report:
- Backend folder layout and where routes live.
- Whether a database exists. If yes: engine, ORM, migration tool. If no: say so.
- The exact endpoint(s) that generate a paper and a worksheet, and how the frontend calls them.
- How the frontend makes API calls (fetch wrapper? axios? where?).
- Router setup and where nav lives.

Done when: a written report in chat, plus a proposed file list for Sections 1–7. **No files changed** (`git status` clean).

---

## Section 1 — Database + users table

Goal: a `users` table and a `stripe_events` table.

If no DB exists: add Postgres via SQLAlchemy + Alembic, using `DATABASE_URL`. Match whatever Section 0 found otherwise.

`users` columns (exact names):
| column | type | notes |
|---|---|---|
| `id` | uuid pk | |
| `clerk_user_id` | text unique not null | |
| `email` | text not null | |
| `plan` | text not null default `'free'` | `'free'` or `'monthly'` only |
| `subscription_status` | text null | raw Stripe status |
| `stripe_customer_id` | text unique null | |
| `stripe_subscription_id` | text unique null | |
| `total_generations` | int not null default 0 | |
| `day_generations` | int not null default 0 | |
| `day_date` | date null | Europe/London date of `day_generations` |
| `created_at` | timestamptz default now() | |

`stripe_events` columns: `id` text pk (Stripe event id), `received_at` timestamptz default now(). Used for webhook idempotency.

Done when: migration applies cleanly on an empty DB and `pytest tests/test_db.py` passes (create a user, read it back, unique constraint on `clerk_user_id` raises).

---

## Section 2 — Backend auth

Goal: every protected endpoint knows the current user.

- A FastAPI dependency `get_current_user` that:
  - reads `Authorization: Bearer <token>`,
  - verifies the Clerk session JWT against `CLERK_JWKS_URL` (signature, `exp`, `nbf`),
  - finds the `users` row by `clerk_user_id`, **creating it on first sight** (fetch email from Clerk if not in the token),
  - returns 401 with `{"detail": {"code": "auth_required"}}` if missing/invalid.
- `GET /api/me` → `{"email", "plan", "total_generations", "day_generations", "free_limit", "daily_limit"}`.
- Apply `get_current_user` to the paper and worksheet generation endpoints.

Done when: `pytest tests/test_auth.py` passes, covering: no header → 401 `auth_required`; bad token → 401; valid token (mock JWKS) → user created once, second call reuses the same row.

---

## Section 3 — Frontend auth

Goal: users sign in with Clerk when they press Generate.

- Wrap the app in `ClerkProvider` using `VITE_CLERK_PUBLISHABLE_KEY`.
- The shared API client attaches `Authorization: Bearer ${await getToken()}` to every `/api` request.
- Pressing Generate while signed out opens Clerk sign-in; after sign-in, the generation proceeds.
- Topic picking and browsing work while signed out.
- Nav shows, when signed in, a pill: exact text `1 free paper` (free, unused), `Free paper used` (free, used), `Unlimited` (monthly). Data from `GET /api/me`.

Done when: `npm run build` passes and, manually, signing in with Google in dev creates exactly one `users` row.

---

## Section 4 — Generation limits

Goal: free users get exactly 1 generation; monthly users get 10/day; no races.

- **Reserve a slot before generating**, in a single atomic SQL `UPDATE … RETURNING`:
  - free: succeed only if `total_generations < FREE_GENERATION_LIMIT`.
  - monthly: if `day_date` ≠ today (Europe/London), reset `day_generations` to 0 and set `day_date`; succeed only if `day_generations < DAILY_GENERATION_LIMIT`.
  - On success increment `total_generations` (and `day_generations`).
- **If generation then fails, refund the slot** (decrement in the same way). A failed generation must not consume the free paper.
- Responses when the reservation fails (exact bodies):
  - free user over limit → **HTTP 402** `{"detail": {"code": "upgrade_required"}}`
  - monthly user over daily cap → **HTTP 429** `{"detail": {"code": "daily_limit_reached"}}`
- Paper and worksheet count the same. The mark scheme for a paper is part of that paper, not a separate generation. Re-downloading an already generated paper costs nothing.

Done when: `pytest tests/test_limits.py` passes, covering: free 1st → 200, 2nd → 402; generation failure refunds; 10 concurrent requests from one free user → exactly 1 succeeds; monthly 10 → 200, 11th → 429; next day resets.

---

## Section 5 — Stripe backend

Goal: checkout, portal, and webhook. Three endpoints.

- `POST /api/billing/checkout` (auth required) → creates a Checkout Session:
  - `mode="subscription"`, `line_items=[{price: STRIPE_PRICE_MONTHLY, quantity: 1}]`
  - `client_reference_id=str(user.id)`
  - `customer=user.stripe_customer_id` if set, else `customer_email=user.email`
  - `success_url=f"{FRONTEND_URL}/account?upgraded=1"`, `cancel_url=f"{FRONTEND_URL}/pricing"`
  - returns `{"url": session.url}`
  - if the user is already `monthly`, return 409 `{"detail": {"code": "already_subscribed"}}`
- `POST /api/billing/portal` (auth required) → Customer Portal session with `return_url=f"{FRONTEND_URL}/account"`, returns `{"url": ...}`. 400 `{"detail": {"code": "no_customer"}}` if no `stripe_customer_id`.
- `POST /api/stripe/webhook` (no auth):
  - verify the signature with `STRIPE_WEBHOOK_SECRET` using the **raw request body**; bad signature → 400.
  - skip if `event.id` already in `stripe_events`; otherwise insert it.
  - `checkout.session.completed` → look up user by `client_reference_id`; set `stripe_customer_id`, `stripe_subscription_id`, `plan='monthly'`, `subscription_status='active'`.
  - `customer.subscription.updated` → find by `stripe_subscription_id`; set `subscription_status`; `plan='monthly'` if status is `active` or `trialing`, else `'free'`.
  - `customer.subscription.deleted` → `plan='free'`, `subscription_status='canceled'`.
  - always return 200 for handled or ignored event types.

Done when: `pytest tests/test_billing.py` passes (mocked Stripe), AND manually:
```
stripe listen --forward-to localhost:8000/api/stripe/webhook
stripe trigger checkout.session.completed
```
shows a 200 in the CLI output.

---

## Section 6 — Frontend: popup, /pricing, /account

Goal: match the agreed mockup.

- **Upgrade popup** (component `UpgradeModal`), opened when any generation call returns 402 `upgrade_required`:
  - title, exact: `You've used your free paper`
  - body: one line saying paid plan gives unlimited papers and worksheets with mark schemes
  - primary button `Continue to payment` → `POST /api/billing/checkout` → `window.location.href = url`
  - secondary link `See all plans` → `/pricing`
  - small text `Secure payment by Stripe`
  - close button with `aria-label="Close"`; Escape closes; focus trapped while open.
- On 429 `daily_limit_reached`: a plain inline message, exact text `You've reached today's limit. It resets at midnight.` No popup.
- After the free paper is generated: an inline note under the download buttons, exact text `That was your free paper.` followed by a link `See plans` → `/pricing`.
- **`/pricing`** (public): two plan cards, Free and Unlimited. Free → `Get your free paper` (links to generate). Unlimited → `Subscribe` (same checkout call; if signed out, sign in first). FAQ: what counts as one paper, cancelling, which exams, who should make the account (a parent or guardian). Prices come from one constant `PRICE_MONTHLY_DISPLAY` so I can change it in one place.
- **`/account`** (signed in only): plan name, status badge, usage line (`Papers today: X of 10` for monthly, `Free papers: X of 1` for free), `Manage subscription` button (portal) for monthly, `Upgrade` link for free, email, Sign out. If URL has `?upgraded=1`, poll `GET /api/me` every 2s for up to 20s until `plan === 'monthly'`, showing `Confirming your payment…` meanwhile.

Done when: `npm run build` passes, and manually in test mode: generate once → generate again → popup → pay with card `4242 4242 4242 4242` → land on /account → plan shows Unlimited → generate works → Manage subscription → cancel → after webhook, plan shows Free.

---

## Section 7 — PDF watermark

Goal: every generated PDF page carries a footer.

- Footer text, exact format: `Generated for {email} · {d MMM yyyy}` e.g. `Generated for jane@example.com · 5 Oct 2026`.
- Small, grey, centred at the bottom of every page of both paper and mark scheme. Must not overlap question content or the existing print headers.
- Email passed from the authenticated user into the render; never from a query param.

Done when: `pytest tests/test_watermark.py` passes — generate a paper as a test user, extract PDF text, assert every page contains `Generated for test@example.com`.

---

## Not in this spec (→ later.md)

- Tutor plan
- Paper packs / credits
- Live-mode Stripe keys and production webhook endpoint (do at deploy)
- Terms of service page with fair-use + no-redistribution clause (I write this myself)
- Usage anomaly checks
