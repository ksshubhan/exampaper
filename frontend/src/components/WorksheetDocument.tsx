import { QuestionBlock } from './PaperPreview'
import type { Worksheet, WorksheetGroup } from '../lib/types'

/** Groups paired with the number their first question takes on the sheet. */
function withNumbering(
  groups: WorksheetGroup[],
): { group: WorksheetGroup; start: number }[] {
  let next = 1
  return groups.map((group) => {
    const start = next
    next += group.questions.length
    return { group, start }
  })
}

/**
 * A worksheet: no cover page, topic-by-topic sections, and questions numbered
 * continuously from 1 so the answer key lines up with the sheet.
 */
export default function WorksheetDocument({
  worksheet,
}: {
  worksheet: Worksheet
}) {
  const numbered = withNumbering(worksheet.groups)
  const tier = worksheet.tier === 'higher' ? 'Higher' : 'Foundation'

  return (
    <>
      <section className="px-12 py-10">
        <header className="border-b-2 border-black pb-3">
          <h1 className="text-xl font-bold">GCSE Maths Worksheet · {tier}</h1>
          <p className="mt-3 text-sm">
            Name ______________________ &nbsp; Date ____________
          </p>
        </header>

        {numbered.map(({ group, start }) => (
          <section key={group.topic_slug} className="mt-8">
            <h2 className="avoid-break mb-4 text-base font-bold uppercase tracking-wide">
              {group.topic}
            </h2>
            {group.questions.map((q, i) => (
              <QuestionBlock
                key={q.id}
                item={q}
                number={start + i}
                showMarks={false}
              />
            ))}
          </section>
        ))}
      </section>

      {worksheet.include_answers && <WorksheetAnswers groups={numbered} />}
    </>
  )
}

/** The answer key, on its own page, under the sheet's own numbering. */
function WorksheetAnswers({
  groups,
}: {
  groups: { group: WorksheetGroup; start: number }[]
}) {
  return (
    <section className="page-break border-t border-neutral-300 px-12 py-10">
      <h2 className="text-xl font-bold">Answers</h2>

      {groups.map(({ group, start }) => (
        <div key={group.topic_slug} className="mt-6">
          <h3 className="text-sm font-bold uppercase tracking-wide text-neutral-600">
            {group.topic}
          </h3>
          <ul className="mt-2 space-y-2">
            {group.questions.map((q, i) => (
              <li key={q.id} className="avoid-break flex gap-3">
                <span className="font-bold">{start + i}</span>
                <div className="flex-1 font-semibold">
                  {q.parts.length === 1 && !q.parts[0]?.label ? (
                    <p>{q.parts[0]?.answer}</p>
                  ) : (
                    q.parts.map((part, k) => (
                      <p key={k}>
                        {part.label && <span className="mr-1">({part.label})</span>}
                        {part.answer}
                      </p>
                    ))
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  )
}
