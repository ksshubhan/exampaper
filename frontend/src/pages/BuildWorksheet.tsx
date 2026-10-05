import { useEffect, useMemo, useRef, useState } from 'react'
import { useAuth, useClerk } from '@clerk/clerk-react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Navigate, useParams } from 'react-router-dom'
import {
  PRACTICE_PATH,
  getBoard,
  getQualification,
  getSubject,
  isSupported,
  practicePath,
  type TierSlug,
} from '../data/catalog'
import Breadcrumb from '../components/Breadcrumb'
import TopicPicker from '../components/TopicPicker'
import { PaperSheet } from '../components/PaperPreview'
import WorksheetDocument from '../components/WorksheetDocument'
import UpgradeModal from '../components/UpgradeModal'
import { generateWorksheet, getTopics, renderPdf } from '../lib/api'
import { generationErrorMessage, isUpgradeRequired } from '../lib/billing'
import { PRESETS, isAvailable, type PresetId } from '../lib/topics'
import type { TopicGroup, Worksheet } from '../lib/types'

const PER_TOPIC_PRESETS = [3, 5, 10]
const DEFAULT_PER_TOPIC = 5
/** Beyond this a worksheet stops being a worksheet (and the build gets slow). */
const MAX_QUESTIONS = 60

/** Serialize every same-origin stylesheet so the PDF renderer has our CSS. */
function collectCss(): string {
  let css = ''
  for (const sheet of Array.from(document.styleSheets)) {
    try {
      for (const rule of Array.from(sheet.cssRules)) css += rule.cssText + '\n'
    } catch {
      // A cross-origin stylesheet we can't read — not ours, skip it.
    }
  }
  return css
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default function BuildWorksheet() {
  const { qualification, board, subject } = useParams()
  const qual = getQualification(qualification)
  const examBoard = getBoard(qualification, board)
  const subj = getSubject(subject)

  const [groups, setGroups] = useState<TopicGroup[]>([])
  const [topicsError, setTopicsError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [activePreset, setActivePreset] = useState<PresetId | null>(null)
  const [calculator, setCalculator] = useState(false)
  const [tier, setTier] = useState<TierSlug>('higher')
  const [perTopic, setPerTopic] = useState(DEFAULT_PER_TOPIC)
  const [includeAnswers, setIncludeAnswers] = useState(true)

  // Generation needs an account. Pressing Generate while signed out opens
  // Clerk's modal and remembers the intent, so the paper is built the moment
  // sign-in completes rather than making the user press the button twice.
  const { isSignedIn } = useAuth()
  const { openSignIn } = useClerk()
  const pendingGenerate = useRef(false)

  const [worksheet, setWorksheet] = useState<Worksheet | null>(null)
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [upgradeOpen, setUpgradeOpen] = useState(false)

  useEffect(() => {
    getTopics()
      .then(setGroups)
      .catch((e) =>
        setTopicsError(e instanceof Error ? e.message : 'Could not load topics.'),
      )
  }, [])

  // A non-calculator worksheet can't use calculator-only topics, and Foundation
  // stops at grade 5. Strands left with nothing drop out entirely.
  const visibleGroups = useMemo(() => {
    return groups
      .map((g) => ({
        ...g,
        topics: g.topics.filter(
          (t) => (calculator || !t.requires_calculator) && isAvailable(t, tier),
        ),
      }))
      .filter((g) => g.topics.length > 0)
  }, [groups, calculator, tier])

  function requestGenerate() {
    if (!isSignedIn) {
      pendingGenerate.current = true
      openSignIn()
      return
    }
    void handleGenerate()
  }

  async function handleGenerate() {
    setLoading(true)
    setError(null)
    try {
      const result = await generateWorksheet({
        qualification: qual!.slug,
        board: examBoard!.slug,
        subject: subj!.slug,
        calculator,
        tier,
        topics: [...selected],
        per_topic: perTopic,
        include_answers: includeAnswers,
      })
      setWorksheet(result)
    } catch (e) {
      // Same limits, same answers as a paper: the popup on a 402, the plain
      // sentence on a 429.
      if (isUpgradeRequired(e)) setUpgradeOpen(true)
      else setError(generationErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  // Sign-in finished while a generation was queued — run it now.
  useEffect(() => {
    if (!isSignedIn || !pendingGenerate.current) return
    pendingGenerate.current = false
    void handleGenerate()
    // handleGenerate is rebuilt every render; depending on it would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSignedIn])

  // Any unknown / mismatched / not-yet-shipped slug -> the practice index.
  if (
    !qual ||
    !examBoard ||
    !subj ||
    !isSupported({
      qualification: qual.slug,
      board: examBoard.slug,
      subject: subj.slug,
    })
  ) {
    return <Navigate to={PRACTICE_PATH} replace />
  }

  const base = practicePath(qual.slug, examBoard.slug, subj.slug)
  const count = selected.size
  const totalQuestions = count * perTopic
  const overCap = totalQuestions > MAX_QUESTIONS

  // Any hand-made change to the selection means it is no longer a preset.
  function toggle(slug: string) {
    setActivePreset(null)
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }

  function setTopics(slugs: string[], select: boolean) {
    setActivePreset(null)
    setSelected((prev) => {
      const next = new Set(prev)
      for (const slug of slugs) {
        if (select) next.add(slug)
        else next.delete(slug)
      }
      return next
    })
  }

  function applyPreset(id: PresetId) {
    const preset = PRESETS[tier].find((p) => p.id === id)
    if (!preset) return
    setSelected(
      new Set(
        visibleGroups
          .flatMap((g) => g.topics)
          .filter((t) => preset.match(t, tier))
          .map((t) => t.slug),
      ),
    )
    setActivePreset(id)
  }

  function clearSelection() {
    setActivePreset(null)
    setSelected(new Set())
  }

  // Keep what the new tier still offers; a preset no longer describes the
  // selection once the pool underneath it changes.
  function changeTier(next: TierSlug) {
    setTier(next)
    setActivePreset(null)
    const unavailable = new Set(
      groups
        .flatMap((g) => g.topics)
        .filter((t) => !isAvailable(t, next))
        .map((t) => t.slug),
    )
    setSelected((prev) => {
      const kept = new Set(prev)
      for (const slug of unavailable) kept.delete(slug)
      return kept
    })
  }

  async function handleDownload() {
    if (!worksheet) return
    setDownloading(true)
    setError(null)
    try {
      const css = collectCss()
      const html = renderToStaticMarkup(
        <PaperSheet>
          <WorksheetDocument worksheet={worksheet} />
        </PaperSheet>,
      )
      saveBlob(await renderPdf(html, css, 'worksheet.pdf'), 'worksheet.pdf')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not build the PDF.')
    } finally {
      setDownloading(false)
    }
  }

  const questionCount = worksheet
    ? worksheet.groups.reduce((n, g) => n + g.questions.length, 0)
    : 0

  return (
    <div className="mx-auto max-w-3xl px-5 py-8">
      <div className="no-print">
        <Breadcrumb
          items={[
            { label: 'Home', to: '/' },
            { label: qual.name, to: practicePath(qual.slug) },
            {
              label: examBoard.name,
              to: practicePath(qual.slug, examBoard.slug),
            },
            { label: subj.name, to: base },
            { label: 'Build a worksheet' },
          ]}
        />

        <h1 className="mt-4 text-2xl font-semibold tracking-tight">
          Build a worksheet
        </h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Pick topics and how many questions you want on each. Every answer is
          checked before it reaches you.
        </p>

        {/* Options */}
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Segmented
            label="Tier"
            value={tier}
            options={[
              { value: 'foundation', label: 'Foundation' },
              { value: 'higher', label: 'Higher' },
            ]}
            onChange={(v) => changeTier(v as TierSlug)}
          />
          <Segmented
            label="Paper type"
            value={calculator ? 'calc' : 'noncalc'}
            options={[
              { value: 'noncalc', label: 'Non-calculator' },
              { value: 'calc', label: 'Calculator' },
            ]}
            onChange={(v) => setCalculator(v === 'calc')}
          />
          <Segmented
            label="Questions per topic"
            value={String(perTopic)}
            options={PER_TOPIC_PRESETS.map((n) => ({
              value: String(n),
              label: String(n),
            }))}
            onChange={(v) => setPerTopic(Number(v))}
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={includeAnswers}
              onChange={(e) => setIncludeAnswers(e.target.checked)}
              className="h-4 w-4 accent-[var(--accent)]"
            />
            Include answers
          </label>
        </div>

        {topicsError && (
          <p className="mt-6 text-sm text-red-500">{topicsError}</p>
        )}

        <TopicPicker
          groups={visibleGroups}
          tier={tier}
          selected={selected}
          activePreset={activePreset}
          onApplyPreset={applyPreset}
          onToggleTopic={toggle}
          onSetTopics={setTopics}
        />

        {/* Sticky summary + action */}
        <div className="sticky bottom-4 z-10 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-lg">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              {count > 0 ? (
                <>
                  <p className="font-semibold">
                    {count} topic{count === 1 ? '' : 's'} selected
                  </p>
                  <p className="mt-0.5 text-sm text-[var(--muted)]">
                    {totalQuestions} questions · {perTopic} per topic ·{' '}
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
                  onClick={clearSelection}
                  className="min-h-11 rounded-xl px-3 text-sm font-medium text-[var(--muted)] transition hover:text-[var(--text)]"
                >
                  Clear
                </button>
              )}
              <button
                type="button"
                onClick={requestGenerate}
                disabled={count === 0 || overCap || loading}
                className="min-h-11 rounded-xl bg-[var(--accent)] px-5 text-sm font-semibold text-[var(--accent-text)] transition active:scale-[0.99] disabled:cursor-not-allowed disabled:bg-[var(--border)] disabled:text-[var(--muted)] disabled:active:scale-100"
              >
                Generate worksheet
              </button>
            </div>
          </div>

          {overCap && (
            <p className="mt-3 text-sm text-red-500">
              Maximum {MAX_QUESTIONS} questions. Choose fewer topics or fewer per
              topic.
            </p>
          )}
        </div>

        {error && <p className="mt-3 text-sm text-red-500">{error}</p>}

        {worksheet?.skipped_topics && worksheet.skipped_topics.length > 0 && (
          <p className="mt-3 text-sm text-[var(--muted)]">
            Not available at Foundation: {worksheet.skipped_topics.join(', ')}
          </p>
        )}

        {worksheet && questionCount > 0 && (
          <div className="mt-6 flex items-center justify-between">
            <p className="text-sm text-[var(--muted)]">
              {questionCount} questions · {worksheet.groups.length} topics
            </p>
            <button
              type="button"
              onClick={handleDownload}
              disabled={downloading}
              className="rounded-xl bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-[var(--accent-text)] transition hover:opacity-90 disabled:opacity-50"
            >
              {downloading ? 'Preparing PDF…' : 'Download worksheet PDF'}
            </button>
          </div>
        )}
      </div>

      {worksheet && questionCount > 0 && (
        <div className="mt-6">
          <PaperSheet>
            <WorksheetDocument worksheet={worksheet} />
          </PaperSheet>
        </div>
      )}

      {upgradeOpen && <UpgradeModal onClose={() => setUpgradeOpen(false)} />}
    </div>
  )
}

function Segmented({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-[var(--muted)]">{label}:</span>
      <div className="flex gap-1 rounded-full border border-[var(--border)] bg-[var(--surface)] p-1">
        {options.map((o) => {
          const active = o.value === value
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => onChange(o.value)}
              aria-pressed={active}
              className={
                'rounded-full px-3 py-1.5 text-sm font-medium transition ' +
                (active
                  ? 'bg-[var(--accent)] text-[var(--accent-text)]'
                  : 'text-[var(--text)] hover:bg-[var(--hover)]')
              }
            >
              {o.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
