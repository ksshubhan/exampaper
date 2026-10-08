# Account status — build spec

Covers both **Before launch** entries in `docs/later.md`: `/pricing` offering
a used free paper, and account status being hard to find. Same workflow as
`docs/before-launch.md`: **one section per prompt**, `/clear` between
sections, commit after each section passes its done-when. **(me)** = Sshubhan,
not Claude Code.

Kickoff prompt for Claude Code sections (1–2):

> Read `docs/account-status.md`. Do Section N only. Stop when its done-when passes and tell me the result.

---

## Decisions (closed)

- **One shared hook, `useMe()`** in `frontend/src/hooks/useMe.ts`: the fetch
  logic lifted out of `PlanPill.tsx` unchanged (fetch once when signed in,
  ignore failures, return `null` when signed out or not loaded). `PlanPill`
  and `Pricing` use it. `Account.tsx` and `BuildPaper.tsx` keep their own
  `getMe()` calls (Account polls after payment; BuildPaper checks before
  generating).
- **`/pricing` shows today's buttons until `/api/me` answers**, and for
  signed-out visitors or a failed `/api/me`. No spinner, no skeleton.
- **The Unlimited card is fixed too.** A subscriber is shown "Subscribe"
  today; the backend already refuses with 409, so this is display only and
  the same class of bug.
- **The header plan pill is the one-tap route, on every screen width.** It
  gets a trailing chevron so it reads as a link. Below `sm` it shows a short
  label (`Unlimited` / `Free`); `sm` and up it shows `planLabel()` as today.
- **The avatar menu gets "Plan and billing"** as its first item, going to
  `/account` via `UserButton.Action` + `useNavigate` (in-app navigation, no
  page reload, no change to `ClerkProvider`). Clerk's own "Manage account"
  and "Sign out" stay, after it.
- **The signed-in phone header must fit.** Estimated today at ~400px wide
  with no pill (it already overflows a 375px phone, so the nav scrolls).
  Room is made below `sm` only: the "ExamPaper" text hides (the logo mark
  stays and still links home), and nav pills go from `px-3.5` to `px-2.5`.
  Desktop is unchanged.

## Fences (all sections)

- Frontend only. No backend, no `limits.py`, no `billing.py`, no API shape
  change, no new env vars, no new npm packages.
- Do not touch `Account.tsx`, `BuildPaper.tsx`, `UpgradeModal.tsx`, or the
  Clerk provider setup in `main.tsx`.
- Every fence in `docs/deploy.md` still applies: never `git checkout .`,
  `git reset --hard`, or `git stash`; don't touch `probe.py`, `.venv*`,
  `resources/`.
- Stripe stays in test mode.

---

## Section 1 — `/pricing` agrees with the account (frontend)

Before starting: commit the pending `docs/later.md` change on its own, message
`Park: account status must be easy to see`.

- Add `useMe()` (see Decisions). `PlanPill.tsx` switches to it with no
  visible change.
- `Pricing.tsx`, Free card, exactly these branches:
  - signed out, loading, or `/api/me` failed → `Get your free paper` link to
    `/` (unchanged).
  - free, `total_generations < free_limit` → unchanged.
  - free, `total_generations >= free_limit` → no link. A muted, non-clickable
    box with the same size as the button: `Free paper used` (the header's
    wording).
  - monthly → the same muted box: `Included in Unlimited`.
- `Pricing.tsx`, Unlimited card:
  - not monthly (incl. signed out / loading / failed) → `Subscribe` button
    (unchanged).
  - monthly → a link to `/account` styled as the secondary button:
    `Manage your plan`. The "Secure payment by Stripe" line hides.
- No other component changes.

Done when: `npm run build` and `npm run lint` pass; Claude Code lists the six
branches with the exact strings as they appear in the code.

---

## Section 2 — Account status in the header (frontend)

- `PlanPill.tsx`: visible at every width (drop `hidden … sm:inline-block`).
  Label: below `sm` → `Unlimited` or `Free`; `sm` and up → `planLabel(me)`.
  Trailing `ChevronRightIcon` (new, in `icons.tsx`, same style as
  `ChevronDownIcon`). `aria-label` = `Account: {planLabel(me)}`.
- `Header.tsx`, below `sm` only: the "ExamPaper" text gets `hidden sm:inline`;
  nav pills `px-2.5 sm:px-3.5`.
- `Header.tsx`: `<UserButton>` gets a `UserButton.MenuItems` with
  `UserButton.Action` label `Plan and billing`, icon `PricingIcon`,
  `onClick` → `navigate('/account')`, placed before
  `<UserButton.Action label="manageAccount" />`.
- Docs: in `docs/later.md`, delete both **Before launch** entries and the
  heading.

Done when: `npm run build` and `npm run lint` pass; Claude Code shows the
header JSX for the signed-in block and states the pill's class string.

---

## Section 3 — Deploy and check (me)

1. Chat reviews the Section 1–2 diffs. Push `main` (one push, one build).
2. Railway deploy log: build passes, healthcheck passes.
3. On `https://exampaper.sshubhan.com`, desktop:
   - Signed out: `/pricing` shows `Get your free paper` and `Subscribe`.
   - Account that used its free paper: header pill `Free paper used ›`;
     `/pricing` Free card `Free paper used`, Unlimited card `Subscribe`.
   - Subscribed test account (`4242 4242 4242 4242`): pill `Unlimited ›`;
     Free card `Included in Unlimited`; Unlimited card `Manage your plan` →
     `/account`.
   - Avatar menu: `Plan and billing` is first and opens `/account` without a
     full page reload.
4. On a real phone, signed in: the pill shows, one tap opens `/account`, and
   the header's Home / Pricing / About icons are all visible without
   side-scrolling.

Done when: every check in 3 and 4 shows exactly what is written there.

---

## Known (not work)

- The header pill reads `/api/me` once per sign-in, so it still says
  `1 free paper` straight after generating until the next page load. Same as
  today.
- `planLabel()` says `1 free paper` even if `free_limit` is raised above 1.
  Same as today.

## Not in this spec

- Everything under **Not now** in `docs/later.md`.
- Stripe live mode (`docs/deploy.md` Section 6).
