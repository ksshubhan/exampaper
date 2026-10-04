import { Navigate, useParams } from 'react-router-dom'
import {
  PRACTICE_PATH,
  SUBJECTS,
  getBoard,
  getQualification,
  isSupported,
  practicePath,
} from '../data/catalog'
import Breadcrumb from '../components/Breadcrumb'
import SubjectCard from '../components/SubjectCard'

export default function SubjectGrid() {
  const { qualification, board } = useParams()
  const qual = getQualification(qualification)
  const examBoard = getBoard(qualification, board)

  // Any unknown / mismatched / not-yet-shipped slug -> the practice index.
  if (
    !qual ||
    !examBoard ||
    !isSupported({ qualification: qual.slug, board: examBoard.slug })
  ) {
    return <Navigate to={PRACTICE_PATH} replace />
  }

  return (
    <div className="mx-auto max-w-5xl px-5 py-8">
      <Breadcrumb
        items={[
          { label: 'Home', to: '/' },
          { label: qual.name, to: practicePath(qual.slug) },
          { label: examBoard.name },
        ]}
      />
      <h1 className="mt-4 text-2xl font-semibold tracking-tight sm:text-3xl">
        {examBoard.name} {qual.name}
      </h1>
      <p className="mt-2 text-[var(--muted)]">Choose a subject.</p>

      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {SUBJECTS.map((s) => (
          <SubjectCard
            key={s.slug}
            to={practicePath(qual.slug, examBoard.slug, s.slug)}
            name={s.name}
            disabled={!isSupported({ subject: s.slug })}
          />
        ))}
      </div>
    </div>
  )
}
