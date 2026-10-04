import type {
  GeneratePaperRequest,
  GenerateWorksheetRequest,
  Paper,
  TopicGroup,
  Worksheet,
} from './types'

/** Fetch the pickable topics, grouped by strand. */
export async function getTopics(): Promise<TopicGroup[]> {
  const res = await fetch('/api/topics')
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
    headers: { 'Content-Type': 'application/json' },
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
    headers: { 'Content-Type': 'application/json' },
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
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    throw new Error(`Worksheet generation failed (${res.status})`)
  }
  return (await res.json()) as Worksheet
}
