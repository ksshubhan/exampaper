// Mirrors backend/app/schema.py. Keep in sync with the Pydantic models.

export interface Diagram {
  svg: string
  alt: string
  not_to_scale: boolean
  plot_grid?: boolean
}

export interface Table {
  caption: string
  headers: string[]
  rows: string[][]
}

export interface MarkSchemeStep {
  code: string
  mark_type: 'M' | 'A' | 'B'
  marks: number
  description: string
  working: string | null
}

export interface Part {
  label: string
  prompt: string
  marks: number
  answer: string
  answer_tolerance: number | null
  working: string
  mark_scheme: MarkSchemeStep[]
}

export interface Metadata {
  archetype: string
  spec_ref: string
  topic: string
  topic_slug: string
  strand: string
  ao: string
  grade_band: string
  seed: number
}

export interface Item {
  id: string
  format: string
  qualification: string
  board: string
  subject: string
  tier: 'foundation' | 'higher'
  calculator: boolean
  total_marks: number
  stem: string
  parts: Part[]
  diagram: Diagram | null
  table: Table | null
  metadata: Metadata
}

// --- Paper assembly (Phase A backend) ---

export interface Topic {
  slug: string
  name: string
  strand: string
  spec_ref: string
  grade_band: string
  typical_marks: number
  archetype_count: number
  requires_calculator: boolean
}

export interface TopicGroup {
  strand: string
  topics: Topic[]
}

export interface Paper {
  id: string
  format: string
  qualification: string
  board: string
  subject: string
  title: string
  tier: 'foundation' | 'higher'
  calculator: boolean
  target_marks: number
  total_marks: number
  duration_minutes: number
  instructions: string[]
  include_answers: boolean
  questions: Item[]
  notes: string[]
  seed: number
}

export interface GeneratePaperRequest {
  format?: string
  qualification?: string
  board?: string
  subject?: string
  tier?: 'foundation' | 'higher'
  calculator?: boolean
  topics: string[]
  target_marks?: number
  include_answers?: boolean
  seed?: number
}

// --- Worksheets ---

export interface GenerateWorksheetRequest {
  qualification?: string
  board?: string
  subject?: string
  tier?: 'foundation' | 'higher'
  calculator?: boolean
  topics: string[]
  per_topic?: number
  include_answers?: boolean
  seed?: number
}

/** One topic's run of questions, easy to hard. */
export interface WorksheetGroup {
  topic: string
  topic_slug: string
  strand: string
  questions: Item[]
}

export interface Worksheet {
  id: string
  qualification?: string
  board?: string
  subject?: string
  title?: string
  tier: 'foundation' | 'higher'
  calculator: boolean
  per_topic: number
  include_answers: boolean
  groups: WorksheetGroup[]
  /** Chosen topics with nothing generatable for this tier / paper type. */
  skipped_topics?: string[]
  notes?: string[]
  seed?: number
}

/** `GET /api/me` — who is signed in, and what they are allowed. */
export interface Me {
  email: string
  plan: 'free' | 'monthly'
  total_generations: number
  day_generations: number
  free_limit: number
  daily_limit: number
}
