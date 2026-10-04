import { Navigate, useParams } from 'react-router-dom'
import {
  PRACTICE_PATH,
  SUBJECTS,
  getBoards,
  getQualification,
  isSupported,
  practicePath,
} from '../data/catalog'
import Breadcrumb from '../components/Breadcrumb'
import NavCard from '../components/NavCard'

export default function BoardGrid() {
  const { qualification } = useParams()
  const qual = getQualification(qualification)

  // Unknown or not-yet-shipped qualification -> the practice index.
  if (!qual || !isSupported({ qualification: qual.slug })) {
    return <Navigate to={PRACTICE_PATH} replace />
  }

  return (
    <div className="mx-auto max-w-5xl px-5 py-8">
      <Breadcrumb
        items={[
          { label: 'Home', to: '/' },
          { label: qual.name },
        ]}
      />
      <h1 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">
        {qual.name}
      </h1>
      <p className="mt-3 max-w-2xl text-[var(--muted)]">
        Choose your exam board.
      </p>

      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {getBoards(qual.slug).map((b) => (
          <NavCard
            key={b.slug}
            to={practicePath(qual.slug, b.slug)}
            title={b.name}
            meta={`${SUBJECTS.length} subjects`}
            action="View subjects"
            disabled={!isSupported({ board: b.slug })}
          />
        ))}
      </div>
    </div>
  )
}
