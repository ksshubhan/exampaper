import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@clerk/clerk-react'
import { getMe } from '../lib/api'
import { planLabel } from '../lib/plan'
import type { Me } from '../lib/types'

/**
 * Plan badge in the nav. Renders nothing until someone is signed in and
 * /api/me has answered, so a signed-out or offline header is unchanged.
 */
export default function PlanPill() {
  const { isLoaded, isSignedIn } = useAuth()
  const [me, setMe] = useState<Me | null>(null)

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return
    let cancelled = false
    getMe()
      .then((account) => {
        if (!cancelled) setMe(account)
      })
      .catch(() => {
        // A failed /api/me just means no badge; it must not break the header.
      })
    return () => {
      cancelled = true
    }
  }, [isLoaded, isSignedIn])

  // Gate on isSignedIn as well as `me`, so a stale badge never outlives a
  // sign-out — that avoids clearing state from inside the effect.
  if (!isSignedIn || !me) return null

  // The badge is also the way to the account page — plan, usage and billing
  // all live behind it.
  return (
    <Link
      to="/account"
      title={me.email}
      className="hidden whitespace-nowrap rounded-full border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--muted)] transition hover:bg-[var(--hover)] hover:text-[var(--text)] sm:inline-block"
    >
      {planLabel(me)}
    </Link>
  )
}
