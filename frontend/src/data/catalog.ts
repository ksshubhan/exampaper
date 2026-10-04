// Single source of truth for the practice hierarchy:
//   qualification  ->  exam board  ->  subject  ->  kind
// Slugs live in the URL; display names are derived from here.

/** What you can build for a subject. The URL's final segment. */
export type KindSlug = 'paper' | 'worksheet'
export type QualificationSlug = 'gcse' | 'a-level' | 'igcse'
export type BoardSlug = 'aqa' | 'edexcel' | 'ocr' | 'wjec' | 'cie'
export type TierSlug = 'foundation' | 'higher'
export type SubjectSlug =
  | 'maths'
  | 'english-language'
  | 'english-literature'
  | 'biology'
  | 'chemistry'
  | 'physics'
  | 'history'
  | 'geography'

export interface Qualification {
  slug: QualificationSlug
  name: string
  description: string
}

export interface Board {
  slug: BoardSlug
  name: string
}

export interface Subject {
  slug: SubjectSlug
  name: string
}

// ---------------------------------------------------------------------------
// What ExamPaper actually supports today.
//
// This is the ONE place that decides it. Everything in the catalog that isn't
// listed here renders as a non-interactive "Coming soon" card, and deep links
// to it bounce back to the Practice page. To ship a new qualification, board,
// subject, tier or kind, add its slug to the matching line below — that is the
// whole change.
export const SUPPORTED: {
  qualifications: QualificationSlug[]
  boards: BoardSlug[]
  subjects: SubjectSlug[]
  tiers: TierSlug[]
  kinds: KindSlug[]
} = {
  qualifications: ['gcse'],
  boards: ['edexcel'],
  subjects: ['maths'],
  tiers: ['foundation', 'higher'],
  kinds: ['paper', 'worksheet'],
}

/** Root of the practice flow, and where an unsupported deep link lands. */
export const PRACTICE_PATH = '/practice'

/** Build a path under /practice from already-validated slugs. */
export function practicePath(...segments: string[]): string {
  return [PRACTICE_PATH, ...segments].join('/')
}

/**
 * True when every slug supplied is one we support. Omitted keys aren't
 * checked, so this serves both a single card (`{ board }`) and a whole route
 * (`{ qualification, board, subject }`).
 */
export function isSupported(selection: {
  qualification?: QualificationSlug
  board?: BoardSlug
  subject?: SubjectSlug
  tier?: TierSlug
  kind?: KindSlug
}): boolean {
  const { qualification, board, subject, tier, kind } = selection
  return (
    (qualification === undefined ||
      SUPPORTED.qualifications.includes(qualification)) &&
    (board === undefined || SUPPORTED.boards.includes(board)) &&
    (subject === undefined || SUPPORTED.subjects.includes(subject)) &&
    (tier === undefined || SUPPORTED.tiers.includes(tier)) &&
    (kind === undefined || SUPPORTED.kinds.includes(kind))
  )
}

export const QUALIFICATIONS: Qualification[] = [
  {
    slug: 'gcse',
    name: 'GCSE',
    description:
      'Years 10–11 qualification taken by students across England, Wales and Northern Ireland.',
  },
  {
    slug: 'a-level',
    name: 'A-Level',
    description:
      'Advanced level qualification for Years 12–13, required for university entry.',
  },
  {
    slug: 'igcse',
    name: 'IGCSE',
    description: 'International GCSE qualification recognised worldwide.',
  },
]

const BOARD_NAMES: Record<BoardSlug, string> = {
  aqa: 'AQA',
  edexcel: 'Edexcel',
  ocr: 'OCR',
  wjec: 'WJEC',
  cie: 'CIE',
}

// Which boards offer each qualification (counts match the real awarding bodies).
const BOARDS_BY_QUAL: Record<QualificationSlug, BoardSlug[]> = {
  gcse: ['aqa', 'edexcel', 'ocr', 'wjec'],
  'a-level': ['aqa', 'edexcel', 'ocr', 'wjec', 'cie'],
  igcse: ['cie', 'edexcel'],
}

export const SUBJECTS: Subject[] = [
  { slug: 'maths', name: 'Maths' },
  { slug: 'english-language', name: 'English language' },
  { slug: 'english-literature', name: 'English literature' },
  { slug: 'biology', name: 'Biology' },
  { slug: 'chemistry', name: 'Chemistry' },
  { slug: 'physics', name: 'Physics' },
  { slug: 'history', name: 'History' },
  { slug: 'geography', name: 'Geography' },
]

export function getQualification(
  slug: string | undefined,
): Qualification | undefined {
  return QUALIFICATIONS.find((q) => q.slug === slug)
}

/** Boards available for a given qualification. */
export function getBoards(qualification: QualificationSlug): Board[] {
  return BOARDS_BY_QUAL[qualification].map((slug) => ({
    slug,
    name: BOARD_NAMES[slug],
  }))
}

/** A board, only if it actually belongs to the given qualification. */
export function getBoard(
  qualification: string | undefined,
  board: string | undefined,
): Board | undefined {
  const qual = getQualification(qualification)
  if (!qual) return undefined
  return getBoards(qual.slug).find((b) => b.slug === board)
}

export function getSubject(slug: string | undefined): Subject | undefined {
  return SUBJECTS.find((s) => s.slug === slug)
}
