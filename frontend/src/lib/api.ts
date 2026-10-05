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

/** The signed-in account: plan, usage and allowances. */
export async function getMe(): Promise<Me> {
  const res = await fetch('/api/me', { headers: await apiHeaders() })
  if (!res.ok) {
    throw new Error(`Could not load your account (${res.status})`)
  }
  return (await res.json()) as Me
}

/** Fetch the pickable topics, grouped by strand. */
export async function getTopics(): Promise<TopicGroup[]> {
  const res = await fetch('/api/topics', { headers: await apiHeaders() })
  if (!res.ok) {
    throw new Error(`Could not load topics (${res.status})`)
  }
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
  if (!res.ok) {
    throw new Error(`PDF render failed (${res.status})`)
  }
  return await res.blob()
}

/** Assemble a full custom paper from the chosen topics. */
export async function generatePaper(req: GeneratePaperRequest): Promise<Paper> {
  const res = await fetch('/api/generate-paper', {
    method: 'POST',
    headers: await apiHeaders(JSON_HEADERS),
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    throw new Error(`Paper generation failed (${res.status})`)
  }
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
  if (!res.ok) {
    throw new Error(`Worksheet generation failed (${res.status})`)
  }
  return (await res.json()) as Worksheet
}
