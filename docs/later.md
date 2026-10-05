# Later

Things deliberately not built yet. Each one is a decision, not a forgotten
task. The build spec is `docs/accounts-and-payments.md`; its pre-deploy gates
are *not* here, because those must ship before the site is public.

## Before launch

- **Set portal cancellation back to end-of-period and show `Cancels on {date}`
  on `/account`.** The Stripe test-mode Customer Portal is currently set to
  cancel immediately, which is what made the Section 6 manual test flip to Free
  the moment the webhook landed. Real customers should keep what they paid for
  until the period ends. That means: switch the portal setting back, then teach
  `/account` the in-between state — `customer.subscription.updated` arrives with
  status `active` and `cancel_at_period_end` true, so the plan stays Unlimited
  and the page needs to say when it stops. Needs `cancel_at_period_end` and
  `current_period_end` stored on `users` and returned by `GET /api/me`, which
  today returns neither.

## Not now

- Tutor plan.
- Paper packs / credits.
- Live-mode Stripe keys and a production webhook endpoint (do at deploy).
- Terms of service page with fair-use + no-redistribution clause (hand-written,
  not generated).
- Usage anomaly checks.
