# Later

Things deliberately not built yet. Each one is a decision, not a forgotten
task. The build spec is `docs/accounts-and-payments.md`; its pre-deploy gates
are *not* here, because those must ship before the site is public.

## Before launch

- **Privacy policy page, then publish the Google OAuth app.** Google will not
  move the ExamPaper OAuth app out of "Testing" until its Branding page links
  a privacy policy on `sshubhan.com`; until then only listed test users can
  use Google sign-in (email magic link works for everyone). UK GDPR expects a
  privacy notice anyway before taking real payments. Hand-written, like the
  terms page: what is collected (email, name, generation counts, plan),
  why, processors (Clerk, Stripe, Railway, Neon), retention, deletion, contact.
  Then add the link in Google Auth Platform → Branding and Publish app.

- **`/pricing` offers "Get your free paper" to an account that has used it.**
  The header chip already says "Free paper used"; the Free card should agree.
  Same class of display issue as the `/account` "3 of 1" bug.

## Not now

- Tutor plan.
- Paper packs / credits.
- Live-mode Stripe keys and a production webhook endpoint (do at deploy).
- Terms of service page with fair-use + no-redistribution clause (hand-written,
  not generated).
- Usage anomaly checks.
