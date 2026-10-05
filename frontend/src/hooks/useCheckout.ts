import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth, useClerk } from '@clerk/clerk-react'
import { startCheckout } from '../lib/api'
import { billingErrorMessage } from '../lib/billing'

/**
 * Subscribing, from wherever it is offered — the upgrade popup and /pricing.
 *
 * Signed out, the first press opens Clerk and the checkout runs itself once
 * sign-in completes: the same remembered-intent pattern the Generate button
 * uses, so nobody has to press a button twice.
 *
 * `error` is the message to show next to the button that was pressed, and
 * `busy` goes back to false when a call fails, so a 503 stays retryable.
 */
export function useCheckout() {
  const { isSignedIn } = useAuth()
  const { openSignIn } = useClerk()
  const pending = useRef(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      // Leaving for Stripe's page; stay busy until the browser navigates.
      window.location.href = await startCheckout()
    } catch (e) {
      setError(billingErrorMessage(e))
      setBusy(false)
    }
  }, [])

  const start = useCallback(() => {
    if (!isSignedIn) {
      pending.current = true
      openSignIn()
      return
    }
    void run()
  }, [isSignedIn, openSignIn, run])

  // Sign-in finished while a checkout was queued — open it now.
  useEffect(() => {
    if (!isSignedIn || !pending.current) return
    pending.current = false
    void run()
  }, [isSignedIn, run])

  return { start, busy, error }
}
