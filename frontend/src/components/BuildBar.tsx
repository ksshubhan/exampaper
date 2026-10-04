import type { Topic } from '../lib/types'

/** Real papers average ~3.8 marks a question, so marks estimate question count. */
const MARKS_PER_QUESTION = 3.8

interface BuildBarProps {
  selectedTopics: Topic[]
  calculator: boolean
  tier: 'foundation' | 'higher'
  loading: boolean
  /** A paper already exists, so the button offers a regenerate instead. */
  hasPaper: boolean
  onClear: () => void
  onGenerate: () => void
}

/**
 * Sticky summary + generate action. Pinned 16px above the viewport bottom so it
 * stays reachable however far down the topic list you are.
 */
export default function BuildBar({
  selectedTopics,
  calculator,
  tier,
  loading,
  hasPaper,
  onClear,
  onGenerate,
}: BuildBarProps) {
  const count = selectedTopics.length
  const marks = selectedTopics.reduce((sum, t) => sum + t.typical_marks, 0)
  const questions = Math.round(marks / MARKS_PER_QUESTION)

  return (
    <div className="sticky bottom-4 z-10 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-lg">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          {count > 0 ? (
            <>
              <p className="font-semibold">
                {count} topic{count === 1 ? '' : 's'} selected
              </p>
              <p className="mt-0.5 text-sm text-[var(--muted)]">
                ≈ {questions} questions · {marks} marks ·{' '}
                {calculator ? 'Calculator' : 'Non-calculator'} ·{' '}
                {tier === 'higher' ? 'Higher' : 'Foundation'}
              </p>
            </>
          ) : (
            <>
              <p className="font-semibold">No topics selected</p>
              <p className="mt-0.5 text-sm text-[var(--muted)]">
                Pick a quick start above, or choose topics.
              </p>
            </>
          )}
        </div>

        <div className="flex items-center gap-1">
          {count > 0 && (
            <button
              type="button"
              onClick={onClear}
              className="min-h-11 rounded-xl px-3 text-sm font-medium text-[var(--muted)] transition hover:text-[var(--text)]"
            >
              Clear
            </button>
          )}
          <button
            type="button"
            onClick={onGenerate}
            disabled={count === 0 || loading}
            className="min-h-11 rounded-xl bg-[var(--accent)] px-5 text-sm font-semibold text-[var(--accent-text)] transition active:scale-[0.99] disabled:cursor-not-allowed disabled:bg-[var(--border)] disabled:text-[var(--muted)] disabled:active:scale-100"
          >
            {loading
              ? 'Assembling…'
              : hasPaper
                ? 'Regenerate paper'
                : 'Generate paper'}
          </button>
        </div>
      </div>
    </div>
  )
}
