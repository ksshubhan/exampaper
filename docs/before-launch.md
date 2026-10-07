# Before launch — build spec

Save as `docs/before-launch.md` in the ExamPaper repo. Same workflow as
`docs/deploy.md`: **one section per prompt**, `/clear` between sections, commit
after each section passes its done-when. Sections marked **(me)** are dashboard
work for Sshubhan, not Claude Code.

Kickoff prompt for Claude Code sections (2–5):

> Read `docs/before-launch.md`. Do Section N only. Stop when its done-when passes and tell me the result.

This spec covers everything in `docs/later.md` under **Before launch** and
**Housekeeping**, plus `docs/deploy.md` Section 5 (custom domain + Clerk
production). It does **not** cover `docs/deploy.md` Section 6 (Stripe live);
this spec is what un-gates it.

---

## Decisions (closed)

- **Order:** the DNS records go in first (Section 1) so their up-to-48 h wait
  runs while the code sections are built. Clerk production is finished last
  (Section 7).
- **One new column, `users.cancel_at`** (timestamptz, nullable): the moment a
  still-active subscription stops. Not the two columns `later.md` suggested
  (`cancel_at_period_end` + `current_period_end`): the page needs one date, and
  Stripe can express a scheduled cancel either way (see Section 4).
- **The plan rule does not change.** A subscription that is `active` with a
  cancel scheduled is still `monthly`. Entitlement still follows `status` only.
- **The free-paper gate does not change.** `limits.py` is right; only the
  `/account` text for a used-up allowance changes.
- **Dependency pinning:** a `uv`-compiled lock file, `backend/requirements.lock`,
  generated from the existing `backend/requirements.txt` (which stays as the
  hand-edited list of floors). The image installs from the lock.
- **The Stripe test-mode Customer Portal stays on cancel at end of period.**
  (`later.md` says it is set to cancel immediately; that line is stale — the
  7 Oct run-through cancelled at period end. Section 1 confirms it.)

## Fences (all sections)

- Every fence in `docs/deploy.md` still applies: do not touch `probe.py`,
  `.venv`, `.venv-dev`, or `resources/`; never `git checkout .`,
  `git reset --hard`, or `git stash`.
- Do not change question generation, sympy verification, blueprints, diagrams,
  auth, `limits.py`, or the render pipeline.
- In `billing.py`, the only change is recording `cancel_at`. Who gets which plan
  stays exactly as it is.
- No new env vars, no new services, no new npm packages.
- Stripe stays in **test mode** for this whole spec.
- The Dockerfile changes only in Section 3, and only the requirements lines.
  No local Docker: Railway's build in Section 6 is the image test, so the diff
  is reviewed before pushing.
- Never paste secrets (`sk_`, `whsec_`, connection strings) into chat. Use XXXX.

---

## Section 1 — Start the DNS clock (me)

1. **Stripe (test mode)** → Settings → Billing → Customer portal →
   Cancellations: confirm **Cancel at end of billing period**. Nothing else.
2. **Railway** → service → Settings → Networking → Custom domain →
   `exampaper.sshubhan.com`. Add **every** record Railway shows (a CNAME, and a
   TXT verification record if it asks) at sshubhan.com's DNS provider.
3. **Clerk** → instance switcher → **Create production instance** (clone the
   development settings), domain `exampaper.sshubhan.com`. Add **every** record
   its Domains page lists.
4. If the DNS provider is Cloudflare: set all of these records to
   **DNS only** (grey cloud). Proxied records fail Clerk's verification.

Do not change any Railway variables yet. The app stays on Clerk development
keys until Section 7.

Done when: the records exist at the DNS provider, and Railway and Clerk both
list the domain (pending is fine — that is the wait this section starts).

---

## Section 2 — Stray files and the README

Goal: nothing in the repo misdescribes it.

- `git rm code.py index.html` (root only — `frontend/index.html` stays).
- Rewrite these parts of `README.md`, and only these:
  - **How it works**, steps 2 and 3: generation is deterministic Python
    (`backend/app/generators/`) with seeded parameters, then SymPy verification.
    No model is called. Read the generators before writing this; describe
    what they do, not what would sound good.
  - **Tech stack** table: drop the Anthropic API. Add what is actually used:
    Postgres (SQLAlchemy + Alembic), Clerk (auth), Stripe (payments),
    Playwright/Chromium (PDF), Railway + Neon (hosting).
  - **Running locally**: Python **3.14**, Node 22, a Postgres database,
    `backend/.env` from `backend/.env.example`, `frontend/.env` from
    `frontend/.env.example`, `alembic upgrade head` before the first run.
    Remove the API-key prerequisite and the `export ANTHROPIC_API_KEY` line.
  - **Tests**: no hard-coded test count. Commands as in the header of
    `backend/requirements-dev.txt`.
  - **Status**: live at `https://exampaper-production.up.railway.app`. Remove
    the "Next: public deployment…" line.
  - The intro and the Disclaimer stay as they are.
- In `docs/later.md`, delete the two Housekeeping entries this section covers
  (stray files, stale README). Leave the dependency entry for Section 3.

Done when: `git status` shows only the two deletions, `README.md` and
`docs/later.md`; `grep -inE "anthropic|llm|api key" README.md` prints nothing;
every file and command the README names exists; `pytest` still passes.

---

## Section 3 — Lock the Python dependencies

Goal: two builds of the same commit install the same packages.

Before this section (me): `uv --version` works; if not, `brew install uv`.

- From the repo root:
  ```
  uv pip compile backend/requirements.txt \
    --python-version 3.14 --python-platform x86_64-unknown-linux-gnu \
    --output-file backend/requirements.lock
  ```
  (Railway's builder is x86_64 Linux; the image is `python:3.14-slim-trixie`.)
- Add a two-line comment at the top of `backend/requirements.txt`: edit floors
  here, then regenerate the lock with the command above.
- `Dockerfile`: copy and install `backend/requirements.lock` instead of
  `backend/requirements.txt`. No other Dockerfile change. Check
  `.dockerignore` does not exclude the lock.
- Test in a **throwaway venv outside the repo**
  (`python3.14 -m venv /tmp/exampaper-lock`), install
  `-r backend/requirements.lock -r backend/requirements-dev.txt`, install
  Playwright's Chromium only if the tests need it, run `pytest` from
  `backend/`, then delete the venv. Do not touch `.venv` or `.venv-dev`.
  If something installs on Linux but not on macOS, stop and report it — do
  not change the target platform.
- In `docs/later.md`, delete the "Python dependencies are unpinned" entry.
  Housekeeping is then empty: delete the heading too.

Done when: `backend/requirements.lock` exists and every line is `==`-pinned;
`git diff Dockerfile` touches only the requirements lines; `pytest` passes in
the throwaway venv; the venv is deleted.

---

## Section 4 — Record the cancel date (backend)

Goal: `GET /api/me` says when a cancelled-but-paid-up subscription stops.

- **Migration `0004_cancel_at`**: `ALTER` to add `users.cancel_at`
  (`timestamptz`, nullable). Reversible. Not an edit to 0001–0003.
- **Model**: `cancel_at: Mapped[datetime | None]`, with a one-line comment.
- **`billing.py`**, a pure helper `subscription_cancel_at(obj) -> datetime | None`:
  1. If `cancel_at` is an int → that, as UTC.
  2. Else if `cancel_at_period_end` is `True` → the period end: the latest
     `current_period_end` across `items.data[]` (current Stripe API versions
     put it there), falling back to a top-level `current_period_end` (older
     versions). The webhook payload uses the **endpoint's** API version, not
     the library's, so both shapes must work.
  3. Else → `None`. Missing or malformed fields give `None`, never an exception.
- `handle_subscription_updated` sets `user.cancel_at` from the helper.
  `handle_subscription_deleted` and the paid branch of
  `handle_checkout_completed` set it to `None`. Nothing else in the handlers
  changes.
- **`/api/me`** adds `"cancel_at"`: ISO-8601 with offset, or `null`.

Tests (`test_billing.py`, `test_db.py` as needed):
- `active` + `cancel_at_period_end: true` + period end on the item → plan stays
  `monthly`, `cancel_at` stored.
- Same with only a top-level `current_period_end` → same result.
- `cancel_at` set directly → stored.
- Renewal (`cancel_at_period_end: false`, `cancel_at: null`) → cleared.
- `customer.subscription.deleted` → cleared, plan `free`.
- Garbage values (string, negative, missing `items`) → `None`, webhook still 200.
- `/api/me` returns `cancel_at` as ISO or `null`.
- The migration's upgrade/downgrade SQL includes the column (existing pattern
  in `test_db.py`).
- Mutation check: revert the `handle_subscription_updated` line by hand, see a
  test fail, restore it.

Done when: `pytest` passes, including the tests above, and the mutation check
was seen to fail.

---

## Section 5 — `/account` shows both states (frontend)

Goal: a cancelling subscriber sees when it ends; an ex-subscriber never sees
"3 of 1".

- `Me` in `frontend/src/lib/types.ts` gains `cancel_at: string | null`.
- In `Account.tsx`, the usage line has exactly these branches:
  - monthly, `cancel_at` null → `Papers today: {day} of {daily_limit}` (unchanged).
  - monthly, `cancel_at` set → the same line, then
    `Cancels on {date}` below it. Badge reads **Cancelling** (amber) instead of
    **Active**. The Manage subscription button stays (it is how you renew).
  - free, `total_generations < free_limit` → `Free papers: {total} of {free_limit}`
    (unchanged).
  - free, `total_generations >= free_limit` → `You've used your free paper.`
    (`free papers` if `free_limit > 1`). No count. The Upgrade button stays.
- `{date}` is `en-GB`, day + long month + year, `timeZone: 'Europe/London'`
  → `7 November 2026`.
- No other component changes.
- Docs: in `docs/later.md`, delete both **Before launch** entries and the
  heading. In `docs/deploy.md` Section 6, change the gate line to point at
  `docs/before-launch.md` Sections 4–5 instead of `later.md`.

Done when: `npm run build` and `npm run lint` pass; Claude Code lists the four
branches with the exact strings as they appear in the code.

---

## Section 6 — Deploy and check, test mode (me)

1. Review the diffs from Sections 2–5 (chat reads them). Push `main`.
2. Railway deploy log: the build installs from `requirements.lock`; the
   pre-deploy applies `0004_cancel_at`; the healthcheck passes.
3. On the Railway URL, fresh private window, an account that has already used
   its free paper:
   - `/account` shows **You've used your free paper.**
   - Upgrade, pay with `4242 4242 4242 4242` → Unlimited, **Active**, no cancel line.
   - Manage subscription → cancel → back on `/account`: **Cancelling**,
     `Cancels on {about a month from today}`, still Unlimited.
   - Manage subscription → renew → cancel line gone, **Active**.
   - Stripe dashboard → cancel the subscription immediately → Free,
     **You've used your free paper.**
   - Stripe webhook page: all 200s.

Done when: every step in 3 shows exactly what is written there.

**Stop point.** All code work is done here. Go on to Section 7 only if Railway
shows the certificate as issued **and** Clerk shows every DNS record verified.
If either is still pending, stop for today; Section 7 is a separate session.

---

## Section 7 — Finish Clerk production (me)

This is `docs/deploy.md` Section 5, steps 2 (from "deploy certificates")
through 5, unchanged. Then, by hand: the README Status line points at
`https://exampaper.sshubhan.com`.

Done when: `docs/deploy.md` Section 5's done-when passes — the Section 4
run-through on `https://exampaper.sshubhan.com`, no Clerk "development mode"
badge, and a sign-in from a Google account never used here.

---

## Known (not work)

- Users from the Clerk **development** instance get new rows when they first
  sign in on production (new `clerk_user_id`). The old rows stay as test data.
- Subscriptions that already had a cancel scheduled before `0004` show no
  date until their next `customer.subscription.updated`. Test data only.

## Not in this spec (→ later.md)

- Stripe live mode (`docs/deploy.md` Section 6) — un-gated by Sections 4–6 here.
- Everything under **Not now** in `docs/later.md`.
