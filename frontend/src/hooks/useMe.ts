import { useEffect, useState } from 'react'
import { useAuth } from '@clerk/clerk-react'
import { getMe } from '../lib/api'
import type { Me } from '../lib/types'

/**
 * Who is signed in, for components that only want to read the plan. Fetches
 * once per sign-in and ignores failures, so `null` covers signed out, not
 * loaded yet, and /api/me being unreachable — a caller shows its default UI.
 */
export function useMe(): Me | null {
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
        // A failed /api/me just means no plan to show; it must not break the
        // page it is on.
      })
    return () => {
      cancelled = true
    }
  }, [isLoaded, isSignedIn])

  // Gate on isSignedIn as well as `me`, so a stale account never outlives a
  // sign-out — that avoids clearing state from inside the effect.
  return isSignedIn ? me : null
}
