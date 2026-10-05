import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import BackLink from '../components/BackLink'
import { useCheckout } from '../hooks/useCheckout'
import { PRICE_MONTHLY_DISPLAY, PRICE_MONTHLY_PERIOD } from '../lib/billing'

/** Public: anyone can read the plans. Subscribing asks for sign-in first. */

const FREE_FEATURES = [
  '1 free paper or worksheet',
  'Mark scheme included',
  'Pick your own topics, tier and length',
]

const UNLIMITED_FEATURES = [
  'Unlimited papers and worksheets',
  'Mark scheme with every one',
  'Fair use: up to 10 a day',
  'Cancel any time',
]

const FAQ: { q: string; a: ReactNode }[] = [
  {
    q: 'What counts as one paper?',
    a: (
      <>
        One generated paper, with its mark scheme — the mark scheme is part of
        the paper, not a second one. A worksheet counts the same as a paper.
        Downloading something you have already generated is free, as often as
        you like.
      </>
    ),
  },
  {
    q: 'Can I cancel?',
    a: (
      <>
        Any time, in two clicks. Open <Link to="/account" className="underline">
          your account
        </Link>{' '}
        and choose Manage subscription — it opens Stripe's own billing page,
        where you can cancel or change your card. You keep unlimited access
        until the subscription ends.
      </>
    ),
  },
  {
    q: 'Which exams does this cover?',
    a: (
      <>
        Edexcel GCSE Maths today, Foundation and Higher, with every topic in the
        specification pickable. More boards and subjects are on the way — the
        homepage shows what is live and what is coming.
      </>
    ),
  },
  {
    q: 'Who should make the account?',
    a: (
      <>
        A parent or guardian. The account holds the subscription and the email
        we put on each PDF, so it should belong to an adult — there are no
        separate student logins to set up.
      </>
    ),
  },
]

export default function Pricing() {
  const { start, busy, error } = useCheckout()

  return (
    <div className="mx-auto max-w-3xl px-5 py-8">
      <BackLink to="/">Home</BackLink>
      <h1 className="mt-4 text-2xl font-semibold tracking-tight">Pricing</h1>
      <p className="mt-3 max-w-xl text-[var(--muted)]">
        Try it on one paper, for free. Subscribe when you want as many as your
        child needs.
      </p>

      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        {/* Free */}
        <PlanCard
          name="Free"
          price="£0"
          period="one paper"
          features={FREE_FEATURES}
        >
          <Link
            to="/"
            className="block rounded-xl border border-[var(--border)] px-5 py-3 text-center text-sm font-semibold text-[var(--text)] transition hover:bg-[var(--hover)]"
          >
            Get your free paper
          </Link>
        </PlanCard>

        {/* Unlimited */}
        <PlanCard
          name="Unlimited"
          price={PRICE_MONTHLY_DISPLAY}
          period={PRICE_MONTHLY_PERIOD}
          features={UNLIMITED_FEATURES}
          highlight
        >
          <button
            type="button"
            onClick={start}
            disabled={busy}
            className="w-full rounded-xl bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-[var(--accent-text)] transition hover:opacity-90 disabled:opacity-50"
          >
            {busy ? 'Opening payment…' : 'Subscribe'}
          </button>
          {error && (
            <p role="alert" className="mt-2 text-sm text-red-500">
              {error}
            </p>
          )}
          <p className="mt-2 text-center text-xs text-[var(--muted)]">
            Secure payment by Stripe
          </p>
        </PlanCard>
      </div>

      <h2 className="mt-10 text-xl font-semibold tracking-tight">
        Questions
      </h2>
      <dl className="mt-4 divide-y divide-[var(--border)] border-y border-[var(--border)]">
        {FAQ.map(({ q, a }) => (
          <div key={q} className="py-4">
            <dt className="text-sm font-semibold">{q}</dt>
            <dd className="mt-1.5 text-sm leading-relaxed text-[var(--muted)]">
              {a}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function PlanCard({
  name,
  price,
  period,
  features,
  highlight = false,
  children,
}: {
  name: string
  price: string
  period: string
  features: string[]
  highlight?: boolean
  children: ReactNode
}) {
  return (
    <div
      className={
        'flex flex-col rounded-2xl border bg-[var(--surface)] p-6 ' +
        (highlight ? 'border-[var(--text)]' : 'border-[var(--border)]')
      }
    >
      <h2 className="text-lg font-semibold tracking-tight">{name}</h2>
      <p className="mt-2 flex items-baseline gap-1.5">
        <span className="text-3xl font-semibold tracking-tight">{price}</span>
        <span className="text-sm text-[var(--muted)]">{period}</span>
      </p>
      <ul className="mt-4 flex-1 space-y-2 text-sm">
        {features.map((feature) => (
          <li key={feature} className="flex gap-2">
            <span aria-hidden className="text-[var(--muted)]">
              ✓
            </span>
            {feature}
          </li>
        ))}
      </ul>
      <div className="mt-6">{children}</div>
    </div>
  )
}
