import { getAuthToken } from './authToken'
import type {
  GeneratePaperRequest,
  GenerateWorksheetRequest,
  Me,
  Paper,
  TopicGroup,
  Worksheet,
} from './types'

/**
 * Headers for an /api call, carrying the Clerk session token when there is one.
 * Signed out, the Authorization header is simply absent, so public endpoints
 * keep working while browsing.
 */
async function apiHeaders(extra: Record<string, string> = {}) {
  const token = await getAuthToken()
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

/**
 * A non-2xx answer from /api, carrying the backend's own error code.
 *
 * The code, not the status, is what the UI switches on: `upgrade_required`
 * opens the upgrade popup, `daily_limit_reached`, `too_many_attempts` and
 * `billing_unavailable` become their own fixed sentences. `message` stays human-readable so an
 * unrecognised failure can still be shown as-is.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string | null

  constructor(status: number, code: string | null, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

/** Raise the right ApiError for a failed response. Never returns. */
async function fail(res: Response, summary: string): Promise<never> {
  let code: string | null = null
  try {
    const body: unknown = await res.json()
    const detail = (body as { detail?: unknown } | null)?.detail
    const value = (detail as { code?: unknown } | null)?.code
    if (typeof value === 'string') code = value
  } catch {
    // An empty body, or HTML from something in front of the API. The status
    // is then all we know, which is enough to show a generic message.
  }
  throw new ApiError(res.status, code, `${summary} (${res.status})`)
}

/** The signed-in account: plan, usage and allowances. */
export async function getMe(): Promise<Me> {
  const res = await fetch('/api/me', { headers: await apiHeaders() })
  if (!res.ok) await fail(res, 'Could not load your account')
  return (await res.json()) as Me
}

/** Fetch the pickable topics, grouped by strand. */
export async function getTopics(): Promise<TopicGroup[]> {
  const res = await fetch('/api/topics', { headers: await apiHeaders() })
  if (!res.ok) await fail(res, 'Could not load topics')
  return (await res.json()) as TopicGroup[]
}

/** Render a document (HTML + its CSS) to a clean PDF blob via headless Chromium. */
export async function renderPdf(
  html: string,
  css: string,
  filename: string,
): Promise<Blob> {
  const res = await fetch('/api/render-pdf', {
    method: 'POST',
    headers: await apiHeaders(JSON_HEADERS),
    body: JSON.stringify({ html, css, filename }),
  })
  if (!res.ok) await fail(res, 'PDF render failed')
  return await res.blob()
}

/** Assemble a full custom paper from the chosen topics. */
export async function generatePaper(req: GeneratePaperRequest): Promise<Paper> {
  const res = await fetch('/api/generate-paper', {
    method: 'POST',
    headers: await apiHeaders(JSON_HEADERS),
    body: JSON.stringify(req),
  })
  if (!res.ok) await fail(res, 'Paper generation failed')
  return (await res.json()) as Paper
}

/** Build a worksheet: N verified questions per chosen topic, grouped by topic. */
export async function generateWorksheet(
  req: GenerateWorksheetRequest,
): Promise<Worksheet> {
  const res = await fetch('/api/generate-worksheet', {
    method: 'POST',
    headers: await apiHeaders(JSON_HEADERS),
    body: JSON.stringify(req),
  })
  if (!res.ok) await fail(res, 'Worksheet generation failed')
  return (await res.json()) as Worksheet
}

/**
 * Open a hosted Stripe Checkout session for the monthly plan.
 *
 * Returns the URL to send the browser to — paying happens on Stripe's page,
 * and the plan is granted by the webhook, not by the redirect back.
 */
export async function startCheckout(): Promise<string> {
  const res = await fetch('/api/billing/checkout', {
    method: 'POST',
    headers: await apiHeaders(),
  })
  if (!res.ok) await fail(res, 'Could not start checkout')
  return ((await res.json()) as { url: string }).url
}

/** Open the Stripe Customer Portal, where a subscriber cancels or updates a card. */
export async function openBillingPortal(): Promise<string> {
  const res = await fetch('/api/billing/portal', {
    method: 'POST',
    headers: await apiHeaders(),
  })
  if (!res.ok) await fail(res, 'Could not open the billing portal')
  return ((await res.json()) as { url: string }).url
}
