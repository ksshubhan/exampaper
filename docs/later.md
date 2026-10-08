# Later

Things deliberately not built yet. Each one is a decision, not a forgotten
task. The build spec is `docs/accounts-and-payments.md`; its pre-deploy gates
are *not* here, because those must ship before the site is public.

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
