/**
 * Bridge between Clerk (a React context) and the API client (plain functions).
 *
 * `ClerkTokenBridge` registers Clerk's `getToken` here once the provider is up;
 * `api.ts` reads it for every request. Before registration — and whenever nobody
 * is signed in — this yields null and the request goes out unauthenticated,
 * which is exactly what public endpoints like /api/topics need.
 */

type TokenGetter = () => Promise<string | null>

let tokenGetter: TokenGetter | null = null

export function setTokenGetter(getter: TokenGetter | null): void {
  tokenGetter = getter
}

/** The current session token, or null when signed out or Clerk isn't ready. */
export async function getAuthToken(): Promise<string | null> {
  if (!tokenGetter) return null
  try {
    return await tokenGetter()
  } catch {
    // A failed refresh must not break a request to a public endpoint.
    return null
  }
}
