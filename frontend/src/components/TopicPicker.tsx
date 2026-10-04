import { useState } from 'react'
import type { TierSlug } from '../data/catalog'
import { PRESETS, gradeLabel, type PresetId } from '../lib/topics'
import type { Topic, TopicGroup } from '../lib/types'
import { CheckIcon, ChevronDownIcon, SearchIcon } from './icons'

const LABEL = 'text-xs font-semibold uppercase tracking-wider text-[var(--muted)]'

interface TopicPickerProps {
  /** Selectable topics, already filtered by the Paper type and tier settings. */
  groups: TopicGroup[]
  /** Drives the quick-start buckets and the capped grade labels. */
  tier: TierSlug
  selected: Set<string>
  activePreset: PresetId | null
  onApplyPreset: (id: PresetId) => void
  onToggleTopic: (slug: string) => void
  /** Select or clear a whole strand at once. */
  onSetTopics: (slugs: string[], select: boolean) => void
}

export default function TopicPicker({
  groups,
  tier,
  selected,
  activePreset,
  onApplyPreset,
  onToggleTopic,
  onSetTopics,
}: TopicPickerProps) {
  const [query, setQuery] = useState('')
  // Every strand starts collapsed; the user opens what they want.
  const [open, setOpen] = useState<Set<string>>(() => new Set())

  const q = query.trim().toLowerCase()
  const searching = q.length > 0
  const allTopics = groups.flatMap((g) => g.topics)

  // Name substring or an exact spec-code hit. With an empty query every topic
  // matches, so searching and browsing share one code path.
  const matches = (t: Topic) =>
    t.name.toLowerCase().includes(q) || t.spec_ref.toLowerCase() === q

  const visible = groups
    .map((g) => ({ ...g, topics: g.topics.filter(matches) }))
    .filter((g) => g.topics.length > 0)

  const allExpanded =
    groups.length > 0 && groups.every((g) => open.has(g.strand))

  function toggleStrand(strand: string) {
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(strand)) next.delete(strand)
      else next.add(strand)
      return next
    })
  }

  return (
    <>
      {/* Quick start */}
      <h2 className={'mt-7 ' + LABEL}>Quick start</h2>
      <div className="mt-2 grid gap-3 sm:grid-cols-3">
        {PRESETS[tier].map((p) => {
          const count = allTopics.filter((t) => p.match(t, tier)).length
          const active = activePreset === p.id
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => onApplyPreset(p.id)}
              aria-pressed={active}
              className={
                'flex min-h-20 flex-col items-start justify-center gap-1 rounded-2xl border p-4 text-left transition ' +
                (active
                  ? 'border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-text)]'
                  : 'border-[var(--border)] bg-[var(--surface)] hover:border-[var(--muted)]')
              }
            >
              <span className="flex items-center gap-2 text-base font-semibold">
                {active && <CheckIcon className="h-4 w-4 shrink-0" />}
                {p.title}
              </span>
              <span
                className={
                  'text-sm ' + (active ? 'opacity-80' : 'text-[var(--muted)]')
                }
              >
                {p.subtitle} · {count} topics
              </span>
            </button>
          )
        })}
      </div>

      {/* Topic list */}
      <div className="mt-7 flex flex-wrap items-center gap-3">
        <h2 className={'mr-auto ' + LABEL}>Or choose topics</h2>
        <div className="relative w-full sm:w-64">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted)]" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search topics, e.g. quadratic"
            aria-label="Search topics"
            className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] pl-9 pr-3 text-sm text-[var(--text)] outline-none transition placeholder:text-[var(--muted)] focus:border-[var(--muted)]"
          />
        </div>
        <button
          type="button"
          onClick={() =>
            setOpen(allExpanded ? new Set() : new Set(groups.map((g) => g.strand)))
          }
          className="min-h-11 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 text-sm font-medium transition hover:border-[var(--muted)]"
        >
          {allExpanded ? 'Collapse all' : 'Expand all'}
        </button>
      </div>

      {searching && visible.length === 0 && (
        <p className="mt-4 text-sm text-[var(--muted)]">
          No topics match "{query.trim()}".
        </p>
      )}

      {/* Leave room for the sticky bar to float clear of the last strand. */}
      <div className="mt-3 space-y-3 pb-28">
        {visible.map((g) => {
          // A search hides non-matching topics, so counts and the strand-level
          // buttons act on what's actually on screen.
          const total = g.topics.length
          const chosen = g.topics.filter((t) => selected.has(t.slug))
          const allChosen = total > 0 && chosen.length === total
          const expanded = searching || open.has(g.strand)
          return (
            <section
              key={g.strand}
              className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)]"
            >
              <div className="flex items-center gap-2 pr-2">
                <button
                  type="button"
                  onClick={() => toggleStrand(g.strand)}
                  aria-expanded={expanded}
                  className="flex min-h-11 flex-1 items-center gap-3 px-4 py-3 text-left"
                >
                  <ChevronDownIcon
                    aria-hidden
                    className={
                      'h-4 w-4 shrink-0 text-[var(--muted)] transition-transform ' +
                      (expanded ? '' : '-rotate-90')
                    }
                  />
                  <span className="font-semibold">{g.strand}</span>
                  {chosen.length > 0 ? (
                    <span className="rounded-full bg-[var(--accent)] px-2.5 py-0.5 text-xs font-medium text-[var(--accent-text)]">
                      {chosen.length} of {total} selected
                    </span>
                  ) : (
                    <span className="text-sm text-[var(--muted)]">
                      {total} topics
                    </span>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() =>
                    onSetTopics(
                      g.topics.map((t) => t.slug),
                      !allChosen,
                    )
                  }
                  className="min-h-11 shrink-0 rounded-xl px-3 text-sm font-medium text-[var(--muted)] transition hover:text-[var(--text)]"
                >
                  {allChosen ? 'Clear all' : 'Select all'}
                </button>
              </div>

              {expanded && (
                <div className="flex flex-wrap gap-2 px-4 pb-4">
                  {g.topics.map((t) => {
                    const on = selected.has(t.slug)
                    return (
                      <button
                        key={t.slug}
                        type="button"
                        onClick={() => onToggleTopic(t.slug)}
                        aria-pressed={on}
                        className={
                          'inline-flex min-h-11 items-center gap-2 rounded-full border px-4 py-2 text-sm transition ' +
                          (on
                            ? 'border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-text)]'
                            : 'border-[var(--border)] bg-[var(--surface)] text-[var(--text)] hover:border-[var(--muted)]')
                        }
                      >
                        {on && <CheckIcon className="h-4 w-4 shrink-0" />}
                        <span className="font-medium">{t.name}</span>
                        <span
                          className={
                            'text-xs ' +
                            (on ? 'opacity-70' : 'text-[var(--muted)]')
                          }
                        >
                          {gradeLabel(t, tier)}
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}
            </section>
          )
        })}
      </div>
    </>
  )
}
