# Privacy policy — build spec

Save as `docs/privacy-policy.md` in the ExamPaper repo. Same workflow as
`docs/before-launch.md`: **one section per prompt**, `/clear` between sections,
commit after each section passes its done-when. Sections marked **(me)** are
Sshubhan's, not Claude Code's.

Kickoff prompt for Claude Code (Section 2 only):

> Read `docs/privacy-policy.md`. Do Section 2 only. Stop when its done-when passes and tell me the result.

This spec covers the first **Before launch** entry in `docs/later.md`: a
privacy policy page, then publishing the Google OAuth app. It does **not**
cover the `/pricing` free-paper entry, the terms page, or Stripe live mode.

---

## Decisions (closed)

- **The policy text is hand-written by Sshubhan**, in `docs/privacy.md`.
  Claude Code transcribes it into the page; it does not write, reword, add or
  remove policy text. Chat checks the draft's *facts* against the code (below),
  not its wording.
- **`docs/privacy.md` is the source of truth.** Any later change edits it
  first, then the page.
- **The page is a normal SPA route, `/privacy`**, styled like `/about`. The
  backend's SPA fallback already serves `index.html` for it on a direct load.
- **One footer, in `App.tsx`**, with a single **Privacy** link. Google expects
  the home page to link the policy; a footer on every page covers that.
- **No cookie banner.** The only cookies are Clerk's session cookies, which
  sign-in cannot work without. No analytics exist.
- **Deletion is by email request**, done by hand (Clerk user, `users` row,
  Stripe customer). No self-serve delete in this spec.
- **No logo on the Google consent screen.** Name, support email, home page,
  privacy link only.

## Fences (all sections)

- Every fence in `docs/deploy.md` still applies: do not touch `probe.py`,
  `.venv`, `.venv-dev`, or `resources/`; never `git checkout .`,
  `git reset --hard`, or `git stash`.
- Frontend only: `main.tsx` (one route), `App.tsx` (footer),
  new `pages/Privacy.tsx`. No backend change, no new npm packages (so no
  markdown renderer — the text is JSX).
- Stripe stays in **test mode**. No Railway variable changes.
- Never paste secrets into chat. Use XXXX.

---

## Facts the policy must match

Read from the code on 7 Oct 2026 (`a7a81cf`). If the draft says something
these don't support, the draft is wrong or the code needs checking first.

- **Our database (Neon, Postgres, London `eu-west-2`)**, table `users`:
  Clerk user id, email, plan, subscription status, cancel date, Stripe
  customer and subscription ids, generation counters (total, per day, render
  and attempt counts with their dates), created-at. Table `stripe_events`:
  Stripe event ids and when they arrived — no personal data.
- **Not stored by us:** name, profile picture, password, card details, the
  papers generated (topics chosen and paper content are not saved).
- **Clerk** (auth): email, and for Google sign-in the name and profile picture
  Google returns (default scopes `openid email profile`). Session cookies.
- **Stripe** (payments): email, card and billing details via Stripe Checkout
  and the Customer Portal. We only ever see the customer and subscription ids.
- **Railway** (hosting, EU West): runs the app; keeps request logs.
  `billing.py` logs the user's email when the monthly plan is granted.
  Check Railway's log retention and whether request logs show client IPs
  before writing the retention line.
- **Google Fonts**: `index.html` loads Lato from `fonts.googleapis.com`, so
  every visitor's browser sends its IP address to Google.
- **Google** (only if signing in with Google): the OAuth sign-in itself.
- No LLM or other AI service receives any data. Generation is local sympy.

## Topics the draft must cover

Wording is Sshubhan's; these are the headings Google and UK GDPR expect.

1. Who runs ExamPaper and how to contact them.
2. What is collected (per the facts above).
3. Why, and the lawful basis (e.g. contract for accounts and payments).
4. Who processes it: Clerk, Stripe, Railway, Neon, Google (sign-in, fonts).
5. Where it is stored, including transfers outside the UK.
6. How long it is kept, including after an account is closed.
7. Your rights, how to request deletion, and the right to complain to the ICO.
8. Cookies.
9. Changes to the policy, and a "Last updated" date.

---

## Section 1 — Write the draft (me)

Write `docs/privacy.md` by hand, using only this formatting so transcription
is mechanical: `#` title, a `Last updated: D Month YYYY` line, `##` headings,
plain paragraphs, `-` bullets, links as bare URLs or email addresses. No
tables, no nested lists, no HTML.

Then chat reads it and checks every factual claim against **Facts** above
(not style, not wording) and that all nine **Topics** are present.

Done when: `docs/privacy.md` exists, chat has found no claim the facts
contradict, and all nine topics are present.

**Stop point.** If this takes the evening, stop here. Section 2 onwards is a
fresh session.

---

## Section 2 — The `/privacy` page and footer

Goal: the text of `docs/privacy.md`, served at `/privacy`, linked from every page.

- New `frontend/src/pages/Privacy.tsx`, same layout as `About.tsx`
  (`BackLink`, `max-w-3xl`, `h1`). Transcribe `docs/privacy.md` **verbatim**:
  `#` → `h1`, `##` → `h2`, paragraphs → `p`, bullets → `ul`/`li`, URLs and
  email addresses → links (`mailto:` for emails). Only JSX escaping may change
  a character. Do not fix, reword, or add text, even if something looks wrong
  — report it instead.
- `main.tsx`: one route, `{ path: 'privacy', element: <Privacy /> }`, next to
  `about`.
- `App.tsx`: a footer below `<main>` with one link, **Privacy** → `/privacy`.
  Muted text, small, matching the existing theme variables. Nothing else in
  the footer.
- No other file changes.

Done when: `npm run build` and `npm run lint` pass; Claude Code lists every
place the page text differs from `docs/privacy.md` (expected: none beyond JSX
escaping) and any text it thinks is wrong but left alone.

---

## Section 3 — Deploy and check (me)

1. Chat reviews the Section 2 diff. Push `main`.
2. Railway build and healthcheck pass.
3. Private window, signed out:
   - `https://exampaper.sshubhan.com/privacy` loads directly (not via a click)
     and shows the full text.
   - The home page footer shows **Privacy**, and it opens `/privacy`.
   - `curl -sI https://exampaper.sshubhan.com/privacy` → `200`.

Done when: all three checks in 3 pass.

---

## Section 4 — Publish the Google OAuth app (me)

1. Google Cloud → project `ExamPaper` → Google Auth Platform → **Branding**:
   app name `ExamPaper`, support email, home page
   `https://exampaper.sshubhan.com`, privacy policy
   `https://exampaper.sshubhan.com/privacy`, authorised domain `sshubhan.com`.
   No logo. Save.
2. **Audience** → **Publish app** → confirm.
3. Production site, private window, a Google account **not** on the test-user
   list: sign in with Google → lands signed in.
4. By hand, in `docs/later.md`: delete the privacy-policy entry. Commit with
   Section 3's push or on its own.

If Google asks for verification or review instead of publishing, **stop** and
note what it asked for. That is a separate session.

Done when: the Audience page shows **In production**, and step 3 signs in.

---

## Not in this spec (→ later.md)

- Self-host Lato, so no visitor IP goes to Google Fonts (then edit the policy).
- Self-serve account deletion / a Clerk `user.deleted` webhook.
- Check whether the ICO data protection fee applies before taking real payments.
- `/pricing` free-paper mismatch; terms page; Stripe live mode — already there.
