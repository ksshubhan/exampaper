import { Navigate, useParams } from 'react-router-dom'
import {
  PRACTICE_PATH,
  getBoard,
  getQualification,
  getSubject,
  isSupported,
  practicePath,
} from '../data/catalog'
import Breadcrumb from '../components/Breadcrumb'
import NavCard from '../components/NavCard'

/** Paper or worksheet, for one subject. */
export default function PracticeChoice() {
  const { qualification, board, subject } = useParams()
  const qual = getQualification(qualification)
  const examBoard = getBoard(qualification, board)
  const subj = getSubject(subject)

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

  return (
    <div className="mx-auto max-w-3xl px-5 py-8">
      <Breadcrumb
        items={[
          { label: 'Home', to: '/' },
          { label: qual.name, to: practicePath(qual.slug) },
          { label: examBoard.name, to: practicePath(qual.slug, examBoard.slug) },
          { label: subj.name },
        ]}
      />
      <h1 className="mt-4 text-2xl font-semibold tracking-tight">{subj.name}</h1>
      <p className="mt-1 text-sm text-[var(--muted)]">
        {examBoard.name} · {qual.name}
      </p>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <NavCard
          to={`${base}/paper`}
          title="Full paper"
          description="An original exam-style paper built from the topics you choose, with a full mark scheme."
          action="Build a paper"
          disabled={!isSupported({ kind: 'paper' })}
        />
        <NavCard
          to={`${base}/worksheet`}
          title="Worksheet"
          description="Focused practice on the topics you choose, ramped easy to hard."
          action="Build a worksheet"
          disabled={!isSupported({ kind: 'worksheet' })}
        />
      </div>
    </div>
  )
}
