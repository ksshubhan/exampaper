import { useEffect, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { RedirectToSignIn, useAuth, useClerk } from '@clerk/clerk-react'
import BackLink from '../components/BackLink'
import { getMe, openBillingPortal } from '../lib/api'
import { billingErrorMessage } from '../lib/billing'
import type { Me } from '../lib/types'

/**
 * The account page: plan, usage, and the way in and out of a subscription.
 *
 * Stripe sends a payer back here as `/account?upgraded=1`, which proves
 * nothing on its own — the plan is granted by the webhook, and that can land a
 * second or two after the redirect. So on `?upgraded=1` we poll /api/me for a
 * short while and say we are confirming, rather than telling someone who just
 * paid that they are on the free plan.
 */

const POLL_INTERVAL_MS = 2000
const CONFIRM_ATTEMPTS = 10 // 10 x 2s = the 20s window

/** `7 November 2026` — UK reader, UK billing day. Null if unparseable. */
function formatCancelDate(iso: string | null): string | null {
  if (!iso) return null
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return null
  return when.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'Europe/London',
  })
}

export default function Account() {
  const { isLoaded, isSignedIn } = useAuth()
  const { signOut } = useClerk()
  const [params] = useSearchParams()
  const upgraded = params.get('upgraded') === '1'

  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(upgraded)
  const [portalBusy, setPortalBusy] = useState(false)
  const [portalError, setPortalError] = useState<string | null>(null)

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return
    let cancelled = false
    let timer: number | undefined

    async function poll(attemptsLeft: number) {
      try {
        const account = await getMe()
        if (cancelled) return
        setMe(account)
        setError(null)
        if (account.plan === 'monthly' || attemptsLeft <= 0) {
          setConfirming(false)
          return
        }
      } catch (e) {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'Could not load your account.')
        if (attemptsLeft <= 0) {
          setConfirming(false)
          return
        }
      }
      timer = window.setTimeout(
        () => void poll(attemptsLeft - 1),
        POLL_INTERVAL_MS,
      )
    }

    // Without `?upgraded=1` there is nothing to wait for: one read, no polling.
    void poll(upgraded ? CONFIRM_ATTEMPTS : 0)

    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [isLoaded, isSignedIn, upgraded])

  async function manageSubscription() {
    setPortalBusy(true)
    setPortalError(null)
    try {
      // Leaving for Stripe's portal; stay busy until the browser navigates.
      window.location.href = await openBillingPortal()
    } catch (e) {
      setPortalError(billingErrorMessage(e))
      setPortalBusy(false)
    }
  }

  if (!isLoaded) return <Shell />
  if (!isSignedIn) return <RedirectToSignIn />

  const monthly = me?.plan === 'monthly'
  // A cancel date only means anything on a subscription that is still running.
  const cancelsOn = monthly ? formatCancelDate(me?.cancel_at ?? null) : null
  // The free allowance is a one-time trial, so it is spent for good (see
  // `_SLOT_AVAILABLE` in limits.py). `total_generations` keeps counting after
  // that, which is why a used-up allowance shows no count at all.
  const freeAllowanceUsed =
    !monthly && me !== null && me.total_generations >= me.free_limit

  return (
    <Shell>
      {confirming && (
        <p className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm text-[var(--muted)]">
          Confirming your payment…
        </p>
      )}

      {error && !me && <p className="mt-4 text-sm text-red-500">{error}</p>}

      {me && (
        <div className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold tracking-tight">
              {monthly ? 'Unlimited' : 'Free'}
            </h2>
            <span
              className={
                'rounded-full px-2.5 py-1 text-xs font-medium ' +
                (monthly
                  ? cancelsOn
                    ? 'bg-amber-100 text-amber-800'
                    : 'bg-green-100 text-green-800'
                  : 'border border-[var(--border)] text-[var(--muted)]')
              }
            >
              {monthly
                ? cancelsOn
                  ? 'Cancelling'
                  : 'Active'
                : 'No subscription'}
            </span>
          </div>

          <p className="mt-3 text-sm text-[var(--muted)]">
            {monthly
              ? `Papers today: ${me.day_generations} of ${me.daily_limit}`
              : freeAllowanceUsed
                ? `You've used your free ${me.free_limit > 1 ? 'papers' : 'paper'}.`
                : `Free papers: ${me.total_generations} of ${me.free_limit}`}
          </p>

          {cancelsOn && (
            <p className="mt-1 text-sm text-[var(--muted)]">
              Cancels on {cancelsOn}
            </p>
          )}

          <div className="mt-5">
            {monthly ? (
              <>
                <button
                  type="button"
                  onClick={() => void manageSubscription()}
                  disabled={portalBusy}
                  className="rounded-xl border border-[var(--border)] px-5 py-3 text-sm font-semibold text-[var(--text)] transition hover:bg-[var(--hover)] disabled:opacity-50"
                >
                  {portalBusy ? 'Opening Stripe…' : 'Manage subscription'}
                </button>
                {portalError && (
                  <p role="alert" className="mt-2 text-sm text-red-500">
                    {portalError}
                  </p>
                )}
              </>
            ) : (
              <Link
                to="/pricing"
                className="inline-block rounded-xl bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-[var(--accent-text)] transition hover:opacity-90"
              >
                Upgrade
              </Link>
            )}
          </div>

          <dl className="mt-6 border-t border-[var(--border)] pt-4 text-sm">
            <dt className="text-[var(--muted)]">Email</dt>
            <dd className="mt-0.5">{me.email}</dd>
          </dl>

          <button
            type="button"
            onClick={() => void signOut()}
            className="mt-5 text-sm text-[var(--muted)] underline decoration-[var(--border)] underline-offset-4 transition hover:text-[var(--text)]"
          >
            Sign out
          </button>
        </div>
      )}
    </Shell>
  )
}

/** The page frame, so the loading and signed-in states do not drift apart. */
function Shell({ children }: { children?: ReactNode }) {
  return (
    <div className="mx-auto max-w-3xl px-5 py-8">
      <BackLink to="/">Home</BackLink>
      <h1 className="mt-4 text-2xl font-semibold tracking-tight">Account</h1>
      {children}
    </div>
  )
}
