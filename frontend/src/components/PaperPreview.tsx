import type { ReactNode } from 'react'
import type { Item, Paper, Part, Table } from '../lib/types'
import { BracketsIcon } from './icons'

/**
 * Renders a Paper as an exam-style sheet. The sheet is always white/black so it
 * matches what prints (the print stylesheet shows only `.printable`). Page
 * breaks and break-avoidance are driven by the `.page-break` / `.avoid-break`
 * classes defined in index.css.
 *
 * The cover follows a familiar exam-paper layout (functional conventions only)
 * but carries ExamPaper's own identity — no awarding-body trade marks, paper
 * codes, or barcodes.
 */
export default function PaperPreview({ paper }: { paper: Paper }) {
  const showScheme = paper.include_answers && paper.questions.length > 0
  return (
    <div className="space-y-8">
      <PaperSheet>
        <PaperDocument paper={paper} />
      </PaperSheet>
      {showScheme && (
        <PaperSheet>
          <MarkSchemeDocument paper={paper} />
        </PaperSheet>
      )}
    </div>
  )
}

/** The white A4 sheet wrapper — one per printable document. */
export function PaperSheet({ children }: { children: ReactNode }) {
  return (
    <div className="printable paper-sheet mx-auto max-w-[820px] bg-white text-black shadow-sm">
      {children}
    </div>
  )
}

/**
 * The question paper: cover + questions. Answers NEVER appear here, so a student
 * who prints/downloads `paper.pdf` never gets the mark scheme.
 */
export function PaperDocument({ paper }: { paper: Paper }) {
  return (
    <>
      <Cover paper={paper} />
      {/* Questions start on a fresh page, after the cover's "Turn over". */}
      <section className="page-break px-12 py-10">
        {paper.questions.map((q, i) => (
          <QuestionBlock key={q.id} item={q} number={i + 1} />
        ))}
        {paper.questions.length > 0 && (
          <p className="avoid-break mt-6 border-t-2 border-black pt-3 text-right text-sm font-bold uppercase tracking-wide">
            Total for the paper is {paper.total_marks}{' '}
            {paper.total_marks === 1 ? 'mark' : 'marks'}
          </p>
        )}
      </section>
    </>
  )
}

/** The mark scheme: its own cover, then the answers + scheme — a separate PDF. */
export function MarkSchemeDocument({ paper }: { paper: Paper }) {
  return (
    <>
      <MarkSchemeCover paper={paper} />
      <Answers paper={paper} />
    </>
  )
}

// --------------------------------------------------------------------------- #
// Cover page
// --------------------------------------------------------------------------- #
function subjectName(slug: string): string {
  if (slug === 'maths') return 'Mathematics'
  return slug.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function formatDuration(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  const parts: string[] = []
  if (h) parts.push(`${h} hour${h === 1 ? '' : 's'}`)
  if (m) parts.push(`${m} minutes`)
  return parts.join(' ') || `${min} minutes`
}

function coverDate(): string {
  const d = new Date()
  const weekday = d.toLocaleDateString('en-GB', { weekday: 'long' })
  const month = d.toLocaleDateString('en-GB', { month: 'long' })
  return `${weekday} ${d.getDate()} ${month} ${d.getFullYear()}`
}

// Shared box styling for the cover (uniform grey rounded borders).
const BOX = 'rounded-[10px] border-[3px] border-[#63676d]'

function Cover({ paper }: { paper: Paper }) {
  const higher = paper.tier === 'higher'

  return (
    <section className="flex min-h-[1040px] flex-col px-10 py-9">
      {/* ---- Top details box ---- */}
      <div className="rounded-[16px] border-[4px] border-[#63676d] p-4">
        {/* Header line — must stay on one line */}
        <p className="text-center text-[13px] font-bold">
          Please check the examination details below before entering your
          candidate information
        </p>

        {/* Candidate surname / Other names — two separate rounded boxes */}
        <div className="mt-3 flex gap-2.5">
          <div className={`${BOX} flex-[1.5] px-3 pb-4 pt-1.5`}>
            <span className="text-[14px]">Candidate surname</span>
          </div>
          <div className={`${BOX} flex-1 px-3 pb-4 pt-1.5`}>
            <span className="text-[14px]">Other names</span>
          </div>
        </div>

        {/* Centre / Candidate number digit boxes */}
        <div className="mt-3 flex gap-12">
          <div>
            <p className="text-[14px]">Centre Number</p>
            <div className="mt-1">
              <DigitBoxes count={5} />
            </div>
          </div>
          <div>
            <p className="text-[14px]">Candidate Number</p>
            <div className="mt-1">
              <DigitBoxes count={4} />
            </div>
          </div>
        </div>

        {/* Title block — a ExamPaper practice paper, not an awarding-body product */}
        <div className="mt-5 flex items-start justify-between gap-4">
          <div>
            <p className="text-[28px] font-black leading-tight tracking-tight">
              ExamPaper Practice Paper
            </p>
            <p className="mt-1.5 text-[18px] font-bold">
              Edexcel-style GCSE (9–1) {higher ? 'Higher' : 'Foundation'} Tier
            </p>
            <p className="text-[18px] font-bold">
              {subjectName(paper.subject)} — Paper{' '}
              {paper.calculator ? '2' : '1'} (
              {paper.calculator ? 'Calculator' : 'Non-Calculator'})
            </p>
            <p className="mt-1.5 text-[15px]">
              Time: {formatDuration(paper.duration_minutes)}
            </p>
            <p className="mt-2 text-[11px] italic text-neutral-500">
              Not affiliated with or endorsed by Pearson Education Ltd.
            </p>
          </div>
          <CalcIcon crossed={!paper.calculator} />
        </div>

        {/* Date */}
        <div className={`${BOX} mt-4 w-[86%] px-4 py-2`}>
          <p className="text-[20px] font-black">{coverDate()}</p>
        </div>

        {/* Equipment + total marks */}
        <div className="mt-3 flex gap-3">
          <div className={`${BOX} flex-1 px-3 py-2 text-[14px] leading-snug`}>
            <strong>You must have:</strong> Ruler graduated in centimetres and
            millimetres, protractor, pair of compasses, pen, HB or B pencil,
            eraser, {paper.calculator ? 'calculator, ' : ''}Formulae Sheet
            (enclosed). Tracing paper may be used.
          </div>
          <div className={`${BOX} w-[120px] px-3 py-2 text-[14px]`}>
            Total Marks
          </div>
        </div>
      </div>

      {/* ---- Instructions / Information / Advice ---- */}
      <div className="mt-6 space-y-5 text-[14px] leading-relaxed">
        <Section
          title="Instructions"
          items={[
            <>
              Use <strong>black</strong> ink or ball-point pen.
            </>,
            <>
              <strong>Fill in the boxes</strong> at the top of this page with
              your name, centre number and candidate number.
            </>,
            <>
              Attempt <strong>all</strong> questions.
            </>,
            <>
              Write your responses in the spaces provided{' '}
              <em>– there may be more space than you need.</em>
            </>,
            <>
              You must <strong>show all your working</strong>.
            </>,
            <>
              Diagrams are <strong>NOT</strong> accurately drawn, unless
              otherwise indicated.
            </>,
            paper.calculator ? (
              <>
                <strong>You may use a calculator.</strong>
              </>
            ) : (
              <>
                <strong>Calculators may not be used.</strong>
              </>
            ),
          ]}
        />
        <Section
          title="Information"
          items={[
            <>The total mark for this paper is {paper.total_marks}.</>,
            <>
              The marks for <strong>each</strong> question are shown in brackets{' '}
              <em>– use this as a guide as to how much time to spend on each question.</em>
            </>,
          ]}
        />
        <Section
          title="Advice"
          items={[
            <>Read each question carefully before you start to answer it.</>,
            <>Try to answer every question.</>,
            <>Check your answers if you have time at the end.</>,
          ]}
        />
      </div>

      {/* ---- Footer: our own mark only, no paper code or barcode ---- */}
      <div className="mt-auto">
        <p className="pb-3 text-right text-sm font-bold italic">Turn over ▸</p>
        <div className="flex items-end justify-between border-t border-neutral-200 pt-3">
          <ExamPaperMark />
        </div>
      </div>
    </section>
  )
}

/** The mark scheme's own cover — a compact title page, its own document. */
function MarkSchemeCover({ paper }: { paper: Paper }) {
  const higher = paper.tier === 'higher'
  return (
    <section className="px-12 py-16">
      <p className="text-[30px] font-black leading-tight tracking-tight">
        ExamPaper Practice Paper
      </p>
      <p className="mt-1.5 text-[22px] font-bold">Mark Scheme</p>
      <div className="mt-6 space-y-1 text-[16px]">
        <p>
          Edexcel-style GCSE (9–1) {higher ? 'Higher' : 'Foundation'} Tier
        </p>
        <p>
          {subjectName(paper.subject)} — Paper {paper.calculator ? '2' : '1'} (
          {paper.calculator ? 'Calculator' : 'Non-Calculator'})
        </p>
        <p>
          Total for this paper: {paper.total_marks}{' '}
          {paper.total_marks === 1 ? 'mark' : 'marks'}
        </p>
      </div>
      <p className="mt-6 text-[11px] italic text-neutral-500">
        Not affiliated with or endorsed by Pearson Education Ltd.
      </p>
    </section>
  )
}

/** A rounded group of connected digit cells (rounded outer, square dividers). */
function DigitBoxes({ count }: { count: number }) {
  return (
    <div className="flex overflow-hidden rounded-[6px] border-[3px] border-[#63676d]">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className={'h-11 w-11' + (i ? ' border-l-[3px] border-[#63676d]' : '')}
        />
      ))}
    </div>
  )
}

/** A scientific-calculator illustration, drawn at a slight angle like the real
 *  paper; crossed out for non-calculator papers. */
function CalcIcon({ crossed }: { crossed: boolean }) {
  const cols = [47, 60, 73, 86, 99]
  const rows = [66, 77, 88, 99, 110, 121, 132]
  return (
    <svg width="150" height="170" viewBox="0 0 150 170" className="shrink-0">
      <g transform="rotate(9 75 90)">
        {/* body */}
        <rect
          x="40"
          y="14"
          width="80"
          height="150"
          rx="9"
          fill="#d7d9dd"
          stroke="#1e1e1e"
          strokeWidth="2.5"
        />
        {/* screen */}
        <rect
          x="47"
          y="31"
          width="66"
          height="26"
          rx="3"
          fill="#cfd6cd"
          stroke="#1e1e1e"
          strokeWidth="1.6"
        />
        {/* buttons */}
        {rows.map((y, r) =>
          cols.map((x, c) => (
            <rect
              key={`${r}-${c}`}
              x={x}
              y={y}
              width="10"
              height="8"
              rx="1.4"
              fill={r < 2 ? '#b7babf' : '#f3f3f4'}
              stroke="#1e1e1e"
              strokeWidth="1"
            />
          )),
        )}
        {crossed && (
          <g stroke="#1e1e1e" strokeWidth="4.5" strokeLinecap="round">
            <line x1="40" y1="14" x2="120" y2="164" />
            <line x1="120" y1="14" x2="40" y2="164" />
          </g>
        )}
      </g>
    </svg>
  )
}

function ExamPaperMark() {
  return (
    <div className="flex flex-col items-center">
      <div className="grid h-8 w-8 place-items-center rounded-md bg-neutral-900 text-white">
        <BracketsIcon className="h-4 w-4" />
      </div>
      <span className="mt-1 text-sm font-bold tracking-tight">ExamPaper</span>
    </div>
  )
}

function Section({ title, items }: { title: string; items: ReactNode[] }) {
  return (
    <div>
      <h2 className="text-lg font-bold">{title}</h2>
      <ul className="mt-1 space-y-1 pl-5">
        {items.map((node, i) => (
          <li key={i} className="relative">
            <span className="absolute -left-4 font-bold">•</span>
            {node}
          </li>
        ))}
      </ul>
    </div>
  )
}

// --------------------------------------------------------------------------- #
// Questions + answers (unchanged layout)
// --------------------------------------------------------------------------- #
export function QuestionBlock({
  item,
  number,
  showMarks = true,
}: {
  item: Item
  number: number
  /** False on a worksheet: no per-part brackets, no question total line. */
  showMarks?: boolean
}) {
  // A question worth 4+ marks starts on a fresh page so its (now generous)
  // working space isn't split across a page break. The first question already
  // opens a new page via the section, so only force it from the second on.
  const startNewPage = number > 1 && item.total_marks >= 4
  // Per-part marks appear only on multi-part questions; a single-part question
  // carries its marks on the closing total line instead.
  const multiPart = item.parts.length > 1
  return (
    <article className={`avoid-break mb-10${startNewPage ? ' page-break' : ''}`}>
      <div className="flex gap-3">
        <span className="text-base font-bold">{number}</span>
        <div className="flex-1">
          {item.stem && (
            <p className="whitespace-pre-line leading-relaxed">{item.stem}</p>
          )}

          {item.table && <DataTable table={item.table} />}

          {item.diagram && (
            <figure className="my-4">
              {/* Fixed-height box above the working space: the SVG scales to
                  fill it (viewBox + default preserveAspectRatio letterboxes),
                  so every diagram occupies the same, predictable band. Graphs
                  and plotting grids get a much larger box — full column width and
                  tall — so they are big enough to read off and plot on. */}
              <div
                className={`mx-auto w-full overflow-hidden [&>svg]:h-full [&>svg]:w-full ${
                  item.diagram.plot_grid ? 'max-w-full' : 'max-w-[280px]'
                }`}
                style={{ height: item.diagram.plot_grid ? '120mm' : '60mm' }}
                role="img"
                aria-label={item.diagram.alt}
                dangerouslySetInnerHTML={{ __html: item.diagram.svg }}
              />
              {item.diagram.not_to_scale && (
                <figcaption className="mt-1 text-center text-xs italic text-neutral-500">
                  Diagram NOT accurately drawn
                </figcaption>
              )}
            </figure>
          )}

          {item.parts.map((part, i) => (
            <div key={i} className="mt-3">
              <p className="leading-relaxed">
                {part.label && (
                  <span className="mr-2 font-semibold">({part.label})</span>
                )}
                {part.prompt}
              </p>
              <AnswerLine part={part} showMarks={showMarks && multiPart} />
            </div>
          ))}
        </div>
      </div>
      {/* Every question closes with its total, then a full-width rule. */}
      {showMarks && (
        <p className="mt-3 text-right text-xs font-semibold text-neutral-600">
          (Total for Question {number} is {item.total_marks}{' '}
          {item.total_marks === 1 ? 'mark' : 'marks'})
        </p>
      )}
      <hr className="mt-2 w-full border-t border-neutral-400" />
    </article>
  )
}

export function DataTable({ table }: { table: Table }) {
  return (
    <figure className="my-5">
      {table.caption && (
        <figcaption className="mb-2 text-center text-base font-semibold">
          {table.caption}
        </figcaption>
      )}
      <div className="overflow-x-auto">
        <table className="mx-auto border-collapse text-base">
          <thead>
            <tr>
              {table.headers.map((h, i) => (
                <th
                  key={i}
                  className="border border-neutral-500 px-5 py-2.5 text-left font-semibold"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td
                    key={c}
                    className="border border-neutral-500 px-5 py-2.5 tabular-nums"
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  )
}

// Units the answer line can pre-print, longest first so "cm²" wins over "cm"
// and "km/h" over "km". The value never comes from a new schema field — it is
// read back out of the answer string the generator already produced.
const ANSWER_UNITS = [
  'g/cm³', 'g/cm²', 'cm³', 'cm²', 'm³', 'm²', 'km/h', 'm/s', 'mph', 'cm',
  'mm', 'km', 'kg', 'ml', 'litres', 'litre', '°', '%', 'm', 'g',
]

/**
 * Derive what to pre-print around a blank answer line from the model answer:
 * a leading prefix ("x =", "£") and/or a trailing unit ("cm²", "°").
 * Compound, sentence, or expression answers get a plain line (no unit),
 * so we never mislabel e.g. "Alice £120, Mel £150" or a coordinate.
 */
function answerFormat(answer: string): { prefix: string; unit: string } {
  const a = answer.trim()
  // Compound / sentence / multi-value answers → plain line (e.g. two-value
  // trig solutions "x = 120° or x = 240°", or "Alice £120, Mel £150").
  if (a.includes(',') || a.includes('\n') || a.includes(' or ') || a.length > 24) {
    return { prefix: '', unit: '' }
  }

  let prefix = ''
  let rest = a

  // Leading variable assignment, e.g. "x = 5", "n = 12", "OP = ...".
  const varMatch = rest.match(/^([A-Za-z]{1,3}[₀-₉]?)\s*=\s*(.+)$/)
  if (varMatch) {
    prefix = `${varMatch[1]} =`
    rest = varMatch[2].trim()
  } else {
    // Currency prefix, e.g. "£4.41", "$108".
    const cur = rest.match(/^([£$])\s*(.+)$/)
    if (cur) {
      prefix = cur[1]
      rest = cur[2].trim()
    }
  }

  // Trailing unit — only when it genuinely closes a quantity (the char before
  // it is a digit/space/bracket, never a letter, so words never match).
  let unit = ''
  for (const u of ANSWER_UNITS) {
    if (rest.endsWith(u)) {
      const before = rest.slice(0, rest.length - u.length)
      if (before === '' || /[\d.\s)²³√±/-]$/.test(before)) {
        unit = u
        break
      }
    }
  }

  return { prefix, unit }
}

/**
 * Working space (in mm) a part earns from its marks: a flat base plus a fixed
 * per-mark allowance, so the space scales with the work asked for and a 1-mark
 * part and a 5-mark part get visibly different room. The space is left blank —
 * no ruled lines — so candidates set out their working freely.
 */
function writingSpaceMm(marks: number): number {
  return 15 + 22 * marks
}

export function AnswerLine({ part, showMarks }: { part: Part; showMarks: boolean }) {
  const { prefix, unit } = answerFormat(part.answer)
  const mm = writingSpaceMm(part.marks)
  return (
    <div className="mt-3 flex flex-col" style={{ minHeight: `${mm}mm` }}>
      {/* Blank working space — no ruled lines; its height is set by the marks. */}
      <div className="flex-1" aria-hidden />
      {/* Final answer line: an unlabelled, right-aligned dotted rule, with the
          answer's prefix/unit pre-printed where the model answer implies one. */}
      <div className="mt-5 flex items-end justify-end gap-2" aria-hidden>
        {prefix && <span className="pb-0.5 text-sm">{prefix}</span>}
        <span
          className="mb-1 border-b border-dotted border-neutral-500"
          style={{ width: '27.5mm' }}
        />
        {unit && <span className="whitespace-nowrap pb-0.5 text-sm">{unit}</span>}
      </div>
      {/* Per-part marks: a bold, right-aligned bracketed number — shown only on
          multi-part questions (single-part marks live on the total line). */}
      {showMarks && (
        <p className="mt-1 text-right text-sm font-bold">({part.marks})</p>
      )}
    </div>
  )
}

function Answers({ paper }: { paper: Paper }) {
  return (
    <section className="page-break border-t border-neutral-300 px-12 py-10">
      <h2 className="text-xl font-bold">Answers and mark scheme</h2>
      <p className="mt-1 text-sm text-neutral-500">{paper.title}</p>

      <ol className="mt-6 space-y-5">
        {paper.questions.map((q, i) => (
          <li key={q.id} className="avoid-break">
            <div className="flex gap-3">
              <span className="font-bold">{i + 1}</span>
              <div className="flex-1">
                <div className="font-semibold">
                  {q.parts.length === 1 && !q.parts[0]?.label ? (
                    <p>{q.parts[0]?.answer}</p>
                  ) : (
                    q.parts.map((part, k) => (
                      <p key={k}>
                        {part.label && (
                          <span className="mr-1">({part.label})</span>
                        )}
                        {part.answer}
                      </p>
                    ))
                  )}
                </div>
                <ul className="mt-1 space-y-0.5 text-sm text-neutral-700">
                  {q.parts.flatMap((part) =>
                    part.mark_scheme.map((step, j) => (
                      <li key={j} className="flex gap-2">
                        <span className="font-mono font-semibold">
                          {step.code}
                        </span>
                        <span>
                          {step.description}
                          {step.working ? ` — ${step.working}` : ''}
                        </span>
                      </li>
                    )),
                  )}
                </ul>
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
