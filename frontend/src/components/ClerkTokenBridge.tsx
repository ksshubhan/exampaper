import { useEffect } from 'react'
import { useAuth } from '@clerk/clerk-react'
import { setTokenGetter } from '../lib/authToken'

/**
 * Hands Clerk's `getToken` to the API client. Renders nothing — it exists only
 * so the token lives behind a React context while `api.ts` stays a set of
 * plain functions any module can call.
 */
export default function ClerkTokenBridge() {
  const { getToken, isLoaded } = useAuth()

  useEffect(() => {
    if (!isLoaded) return
    setTokenGetter(() => getToken())
    return () => setTokenGetter(null)
  }, [getToken, isLoaded])

  return null
}
