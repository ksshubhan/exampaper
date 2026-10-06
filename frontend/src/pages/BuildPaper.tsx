import { useEffect, useMemo, useRef, useState } from 'react'
import { useAuth, useClerk } from '@clerk/clerk-react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Link, Navigate, useParams } from 'react-router-dom'
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
import BuildBar from '../components/BuildBar'
import TopicPicker from '../components/TopicPicker'
import PaperPreview, {
  MarkSchemeDocument,
  PaperDocument,
  PaperSheet,
} from '../components/PaperPreview'
import UpgradeModal from '../components/UpgradeModal'
import { generatePaper, getMe, getTopics, renderPdf } from '../lib/api'
import {
  downloadErrorMessage,
  generationErrorMessage,
  isUpgradeRequired,
} from '../lib/billing'
import { PRESETS, isAvailable, type PresetId } from '../lib/topics'
import type { Paper, TopicGroup } from '../lib/types'

const MARK_PRESETS = [25, 40, 60, 80]

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

export default function BuildPaper() {
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
  const [targetMarks, setTargetMarks] = useState(80)
  const [includeAnswers, setIncludeAnswers] = useState(true)

  // Generation needs an account. Pressing Generate while signed out opens
  // Clerk's modal and remembers the intent, so the paper is built the moment
  // sign-in completes rather than making the user press the button twice.
  const { isSignedIn } = useAuth()
  const { openSignIn } = useClerk()
  const pendingGenerate = useRef(false)

  const [paper, setPaper] = useState<Paper | null>(null)
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The 402 opens the popup; the free-paper note is whatever /api/me says
  // about the allowance once the paper is in hand.
  const [upgradeOpen, setUpgradeOpen] = useState(false)
  const [freePaperUsed, setFreePaperUsed] = useState(false)

  useEffect(() => {
    getTopics()
      .then(setGroups)
      .catch((e) =>
        setTopicsError(e instanceof Error ? e.message : 'Could not load topics.'),
      )
  }, [])

  // A non-calculator paper can't use calculator-only topics, and Foundation
  // stops at grade 5. Strands left with nothing drop out entirely.
  const visibleGroups = useMemo(() => {
    return groups
      .map((g) => ({
        ...g,
        topics: g.topics.filter(
          (t) =>
            (calculator || !t.requires_calculator) && isAvailable(t, tier),
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
      const result = await generatePaper({
        // format is omitted: the backend already defaults it to the only
        // value the frontend ever sent.
        qualification: qual!.slug,
        board: examBoard!.slug,
        subject: subj!.slug,
        calculator,
        tier,
        topics: [...selected],
        target_marks: targetMarks,
        include_answers: includeAnswers,
      })
      setPaper(result)
      void checkAllowance()
    } catch (e) {
      // 402 is not an error to read, it is an offer: the popup, not red text.
      if (isUpgradeRequired(e)) setUpgradeOpen(true)
      else setError(generationErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  /** Was that the free paper? The backend owns the count, so ask it. */
  async function checkAllowance() {
    try {
      const me = await getMe()
      setFreePaperUsed(me.plan === 'free' && me.total_generations >= me.free_limit)
    } catch {
      // The note is a courtesy; a failed /api/me must not look like a failed
      // paper, which is sitting right there on the page.
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

  // Any hand-made change to the selection means it is no longer a preset.
  function toggle(slug: string) {
    setActivePreset(null)
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(slug) ? next.delete(slug) : next.add(slug)
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

  // A preset replaces the selection outright, drawn from what the current
  // Paper type setting actually offers.
  function applyPreset(id: PresetId) {
    const preset = PRESETS[tier].find((p) => p.id === id)
    if (!preset) return
    const slugs = visibleGroups
      .flatMap((g) => g.topics)
      .filter((t) => preset.match(t, tier))
      .map((t) => t.slug)
    setSelected(new Set(slugs))
    setActivePreset(id)
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

  function clearSelection() {
    setActivePreset(null)
    setSelected(new Set())
  }

  // Marks come off every selected topic, including any the Paper type filter
  // currently hides, so the summary matches what gets sent.
  const selectedTopics = groups
    .flatMap((g) => g.topics)
    .filter((t) => selected.has(t.slug))

  async function handleDownload() {
    if (!paper) return
    setDownloading(true)
    setError(null)
    try {
      const css = collectCss()
      // The question paper — never contains answers.
      const paperHtml = renderToStaticMarkup(
        <PaperSheet>
          <PaperDocument paper={paper} />
        </PaperSheet>,
      )
      saveBlob(await renderPdf(paperHtml, css, 'paper.pdf'), 'paper.pdf')
      // The mark scheme ships as its own separate PDF.
      if (paper.include_answers) {
        const schemeHtml = renderToStaticMarkup(
          <PaperSheet>
            <MarkSchemeDocument paper={paper} />
          </PaperSheet>,
        )
        saveBlob(
          await renderPdf(schemeHtml, css, 'mark-scheme.pdf'),
          'mark-scheme.pdf',
        )
      }
    } catch (e) {
      setError(downloadErrorMessage(e))
    } finally {
      setDownloading(false)
    }
  }

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
            { label: 'Build a paper' },
          ]}
        />

        <h1 className="mt-4 text-2xl font-semibold tracking-tight">
          Build a custom paper
        </h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Pick a quick start or choose your own topics. We assemble an original{' '}
          {examBoard.name} {qual.name} {subj.name} paper, ramped easy to hard.
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
            label="Length"
            value={String(targetMarks)}
            options={MARK_PRESETS.map((m) => ({
              value: String(m),
              label: `${m} marks`,
            }))}
            onChange={(v) => setTargetMarks(Number(v))}
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={includeAnswers}
              onChange={(e) => setIncludeAnswers(e.target.checked)}
              className="h-4 w-4 accent-[var(--accent)]"
            />
            Include answers &amp; mark scheme
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

        <BuildBar
          selectedTopics={selectedTopics}
          calculator={calculator}
          tier={tier}
          loading={loading}
          hasPaper={paper !== null}
          onClear={clearSelection}
          onGenerate={requestGenerate}
        />

        {error && <p className="mt-3 text-sm text-red-500">{error}</p>}

        {paper && paper.notes.length > 0 && (
          <div className="mt-5 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
            {paper.notes.map((n, i) => (
              <p key={i}>{n}</p>
            ))}
          </div>
        )}

        {paper && paper.questions.length > 0 && (
          <div className="mt-6 flex items-center justify-between">
            <p className="text-sm text-[var(--muted)]">
              {paper.questions.length} questions · {paper.total_marks} marks ·{' '}
              {paper.duration_minutes} min
            </p>
            <button
              type="button"
              onClick={handleDownload}
              disabled={downloading}
              className="rounded-xl bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-[var(--accent-text)] transition hover:opacity-90 disabled:opacity-50"
            >
              {downloading
                ? 'Preparing PDF…'
                : paper.include_answers
                  ? 'Download paper + mark scheme'
                  : 'Download paper PDF'}
            </button>
          </div>
        )}

        {paper && paper.questions.length > 0 && freePaperUsed && (
          <p className="mt-3 text-sm text-[var(--muted)]">
            That was your free paper.{' '}
            <Link
              to="/pricing"
              className="font-medium text-[var(--text)] underline decoration-[var(--border)] underline-offset-4 transition hover:decoration-[var(--text)]"
            >
              See plans
            </Link>
          </p>
        )}
      </div>

      {upgradeOpen && <UpgradeModal onClose={() => setUpgradeOpen(false)} />}

      {paper && paper.questions.length > 0 && (
        <div className="mt-6">
          <PaperPreview paper={paper} />
        </div>
      )}
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
