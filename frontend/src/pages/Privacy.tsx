import BackLink from '../components/BackLink'

// The text below is a verbatim transcription of docs/privacy.md, which is the
// source of truth: change that file first, then this page.
const linkClass =
  'underline underline-offset-2 transition-colors hover:text-[var(--text)]'

export default function Privacy() {
  return (
    <div className="mx-auto max-w-3xl px-5 py-8">
      <BackLink to="/">Home</BackLink>
      <h1 className="mt-4 text-2xl font-semibold tracking-tight">
        Privacy policy
      </h1>
      <p className="mt-3 text-[var(--muted)]">Last updated: 8 October 2026.</p>

      <h2 className="mt-8 text-lg font-semibold tracking-tight">Who we are</h2>
      <p className="mt-3 text-[var(--muted)]">Sshubhan Kammari</p>
      <p className="mt-3 text-[var(--muted)]">
        <a href="mailto:ksshubhan@gmail.com" className={linkClass}>
          ksshubhan@gmail.com
        </a>
      </p>
      <p className="mt-3 text-[var(--muted)]">
        ExamPaper is an app that generates exam papers in the style of past
        papers, as many as you want.
      </p>

      <h2 className="mt-8 text-lg font-semibold tracking-tight">
        What we collect
      </h2>
      <p className="mt-3 text-[var(--muted)]">
        We ask for your email, your plan, subscription status and cancel date,
        your Clerk account ID, Stripe customer and subscription IDs, usage
        counts and the day your account was created.
      </p>

      <h2 className="mt-8 text-lg font-semibold tracking-tight">
        Why we collect it
      </h2>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-[var(--muted)]">
        <li>
          Contract: We need the data to provide the service you signed up for.
          This covers the account, email, plan, usage counts and Stripe IDs.
        </li>
        <li>
          Legal obligation: the law requires us to keep it. This covers payment
          records kept for tax.
        </li>
        <li>
          Legitimate interests: We have a reasonable need that doesn't override
          your privacy. This covers server logs (keeping the site running and
          secure) and loading the font from Google.
        </li>
      </ul>

      <h2 className="mt-8 text-lg font-semibold tracking-tight">
        Who processes it
      </h2>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-[var(--muted)]">
        <li>
          Clerk: holds your email and if signed in with Google your name and
          profile picture as well.
        </li>
        <li>
          Stripe: holds your card and billing details; we never see the card.
        </li>
        <li>
          Railway: keeps server logs and these include the email of anyone who
          subscribes, and may include IP addresses.
        </li>
        <li>Neon: hosts the database.</li>
        <li>
          Google: Google sign-in, and loading the website's font, which sends
          the visitor's IP address to Google.
        </li>
      </ul>

      <h2 className="mt-8 text-lg font-semibold tracking-tight">
        Where it is stored
      </h2>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-[var(--muted)]">
        <li>Database: Neon, London.</li>
        <li>App: Railway, EU West. Amsterdam, Netherlands.</li>
        <li>
          Clerk and Stripe are US companies, so some data is transferred outside
          the UK.
        </li>
      </ul>

      <h2 className="mt-8 text-lg font-semibold tracking-tight">
        How long we keep it
      </h2>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-[var(--muted)]">
        <li>While you have an account we keep your data.</li>
        <li>
          When someone asks to be deleted we remove you from Clerk, from the
          database and as a customer in Stripe within 30 days.
        </li>
        <li>
          If you don't sign in within 2 years we assume that you no longer use
          the account and your details will be deleted.
        </li>
        <li>
          Stripe keeps payment records for tax purposes, even after an account
          is deleted.
        </li>
        <li>Server logs: Railway deletes them after 7 days.</li>
      </ul>

      <h2 className="mt-8 text-lg font-semibold tracking-tight">
        Your rights
      </h2>
      <p className="mt-3 text-[var(--muted)]">Under the UK GDPR:</p>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-[var(--muted)]">
        <li>You can ask for a copy of the data we hold.</li>
        <li>You can ask us to correct wrong data.</li>
        <li>You can ask us to delete your data.</li>
        <li>
          You can ask us to stop using your data while a dispute is being sorted
          out.
        </li>
        <li>You can ask for your data in a machine-readable format.</li>
        <li>You can object to processing based on legitimate interests.</li>
        <li>
          To use any of these rights, email{' '}
          <a href="mailto:ksshubhan@gmail.com" className={linkClass}>
            ksshubhan@gmail.com
          </a>
          .
        </li>
        <li>Expect replies within one month.</li>
        <li>
          You can complain to the ICO at{' '}
          <a
            href="https://ico.org.uk"
            target="_blank"
            rel="noreferrer"
            className={linkClass}
          >
            ico.org.uk
          </a>
          .
        </li>
      </ul>

      <h2 className="mt-8 text-lg font-semibold tracking-tight">Cookies</h2>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-[var(--muted)]">
        <li>
          Clerk's sign-in cookies keep people signed in and sign-in cannot work
          without them.
        </li>
        <li>
          The site stores the light/dark choice in the browser's local storage.
        </li>
        <li>No analytics, advertising or tracking.</li>
      </ul>

      <h2 className="mt-8 text-lg font-semibold tracking-tight">
        Changes to this policy
      </h2>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-[var(--muted)]">
        <li>Our policy may be subject to change from time to time.</li>
        <li>
          The "Last updated" date at the top shows when it last changed.
        </li>
        <li>
          We will inform you via email when significant changes to our policy
          are made.
        </li>
      </ul>
    </div>
  )
}
