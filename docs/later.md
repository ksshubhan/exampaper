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

- **`/account` shows "Free papers: 3 of 1" to a former subscriber.**
  `total_generations` is a lifetime counter and increments on every generation,
  subscriber or not (`_SLOT_AVAILABLE` in `backend/app/limits.py`), while
  `Account.tsx` renders `Free papers: {total_generations} of {free_limit}` for
  anyone not on the monthly plan. So someone who subscribed, generated three
  papers and then cancelled is told they have used 3 of 1. The *gate* is right —
  free papers are a one-time trial, `total_generations < free_limit`, and a
  returning ex-subscriber is correctly out of them — so this is a display
  problem, not a limits one. The page needs a third state for "free allowance
  already used" rather than a count that reads as broken arithmetic. Lands in
  the same component and the same lifecycle as the cancellation work above, so
  it is worth doing in that pass; it surfaces the moment anyone cancels, which
  is Section 6's own done-when.

## Not now

- Tutor plan.
- Paper packs / credits.
- Live-mode Stripe keys and a production webhook endpoint (do at deploy).
- Terms of service page with fair-use + no-redistribution clause (hand-written,
  not generated).
- Usage anomaly checks.
