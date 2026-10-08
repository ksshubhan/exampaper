# Later

Things deliberately not built yet. Each one is a decision, not a forgotten
task. The build spec is `docs/accounts-and-payments.md`; its pre-deploy gates
are *not* here, because those must ship before the site is public.

## Before launch

- **`/pricing` offers "Get your free paper" to an account that has used it.**
  The header chip already says "Free paper used"; the Free card should agree.
  Same class of display issue as the `/account` "3 of 1" bug.

- **Account status must be easy to see.** A signed-in user should see their
  plan and usage, and reach `/account` (billing, cancel), in one tap from any
  page, on phone and desktop. Today the only way is the header plan badge
  (`PlanPill.tsx`), which doesn't look like a link and is hidden below the
  `sm` breakpoint, so phones have no route at all. Clerk's avatar menu
  "Manage account" opens Clerk's profile, not `/account`; a custom menu item
  there is one option.

## Not now

- **Delete accounts unused for 2 years.** `docs/privacy.md` promises it. Nothing
  does it yet: check Clerk's last-sign-in dates by hand (first due Oct 2028),
  or build it.
- Self-host Lato, so no visitor IP goes to Google Fonts (then edit the policy).
- Self-serve account deletion / a Clerk `user.deleted` webhook (deletion is by
  email request for now).
- Check whether the ICO data protection fee applies before taking real payments.
- Tutor plan.
- Paper packs / credits.
- Live-mode Stripe keys and a production webhook endpoint (do at deploy).
- Terms of service page with fair-use + no-redistribution clause (hand-written,
  not generated).
- Usage anomaly checks.
