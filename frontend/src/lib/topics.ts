import type { TierSlug } from '../data/catalog'
import type { Topic } from './types'

/** Foundation tops out at grade 5 — the same cut the backend assembler makes. */
export const FOUNDATION_MAX_GRADE = 5

/**
 * Grade bands arrive from /topics as a plain "lo-hi" string — "4-6". Pull the
 * numbers out rather than splitting on the hyphen, so a future "grade 4-6" or
 * an en-dashed "4–6" reads the same, and a single-grade band ("7") works too.
 */
export function parseGradeBand(band: string): { lo: number; hi: number } | null {
  const nums = band.match(/\d+/g)
  if (!nums) return null
  return { lo: Number(nums[0]), hi: Number(nums[nums.length - 1]) }
}

/**
 * Whether a topic appears at all on this tier. Foundation carries anything
 * starting at grade 5 or below; Higher carries everything.
 */
export function isAvailable(topic: Topic, tier: TierSlug): boolean {
  if (tier === 'higher') return true
  const band = parseGradeBand(topic.grade_band)
  return band !== null && band.lo <= FOUNDATION_MAX_GRADE
}

/** A topic's band as this tier presents it: Foundation clamps the top to 5. */
export function tierGradeBand(
  topic: Topic,
  tier: TierSlug,
): { lo: number; hi: number } | null {
  const band = parseGradeBand(topic.grade_band)
  if (!band) return null
  if (tier === 'foundation') {
    return { lo: band.lo, hi: Math.min(band.hi, FOUNDATION_MAX_GRADE) }
  }
  return band
}

/** Midpoint of the tier-capped band — the number the presets bucket on. */
export function gradeMid(topic: Topic, tier: TierSlug): number | null {
  const band = tierGradeBand(topic, tier)
  return band ? (band.lo + band.hi) / 2 : null
}

/** "Grade 3–5", or "Grade 5" once capping collapses the range. */
export function gradeLabel(topic: Topic, tier: TierSlug): string {
  const band = tierGradeBand(topic, tier)
  if (!band) return ''
  return band.lo === band.hi
    ? `Grade ${band.lo}`
    : `Grade ${band.lo}–${band.hi}`
}

export type PresetId = 'full' | 'core' | 'hardest' | 'essentials' | 'top'

export interface Preset {
  id: PresetId
  title: string
  subtitle: string
  /** Whether this preset includes the topic on the given tier. */
  match: (topic: Topic, tier: TierSlug) => boolean
}

/** Quick starts per tier — the grade buckets differ because the ceiling does. */
export const PRESETS: Record<TierSlug, Preset[]> = {
  higher: [
    {
      id: 'full',
      title: 'Full paper',
      subtitle: 'Every Higher topic',
      match: () => true,
    },
    {
      id: 'core',
      title: 'Grades 4–6',
      subtitle: 'Core Higher topics',
      match: (t, tier) => {
        const mid = gradeMid(t, tier)
        return mid !== null && mid >= 4 && mid < 6.5
      },
    },
    {
      id: 'hardest',
      title: 'Grades 7–9',
      subtitle: 'The hardest topics',
      match: (t, tier) => {
        const mid = gradeMid(t, tier)
        return mid !== null && mid >= 6.5
      },
    },
  ],
  foundation: [
    {
      id: 'full',
      title: 'Full paper',
      subtitle: 'Every Foundation topic',
      match: () => true,
    },
    {
      id: 'essentials',
      title: 'Grades 1–3',
      subtitle: 'The essentials',
      match: (t, tier) => {
        const mid = gradeMid(t, tier)
        return mid !== null && mid < 3.5
      },
    },
    {
      id: 'top',
      title: 'Grades 4–5',
      subtitle: 'Top Foundation topics',
      match: (t, tier) => {
        const mid = gradeMid(t, tier)
        return mid !== null && mid >= 3.5
      },
    },
  ],
}
