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
- Tutor plan.
- Paper packs / credits.
- Usage anomaly checks.
- Sign-in button on phones for signed-out visitors (the header one is hidden
  below `sm`). New users are covered by Generate / Subscribe / `/account`;
  only a returning user who just wants to sign in has no direct route.
- **EU VAT.** A UK seller owes VAT from the first B2C digital sale to an EU
  consumer (non-Union OSS; the €10k threshold is for EU-established sellers
  only). Check with HMRC or an accountant before marketing outside the UK.
- **Stripe Radar Standard.** Left on Radar Lite (included). Standard is
  £0.04 per screened transaction, renewals included — a new paid service.
- **Shared Stripe product description.** ExamPaper's live account shares a
  legal entity with my Edumentors payout (Express) account, so both carry
  "Tutoring services via EDUMENTORS.co.uk platform." Change it only if
  Stripe asks what ExamPaper sells; any edit shows on both.
