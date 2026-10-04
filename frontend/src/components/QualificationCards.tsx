import { QUALIFICATIONS, getBoards, isSupported, practicePath } from '../data/catalog'
import NavCard from './NavCard'

/**
 * The qualification chooser — GCSE / A-Level / IGCSE, with the Coming soon
 * treatment for the two that aren't shipped. Layout-neutral: the caller owns
 * the surrounding spacing.
 */
export default function QualificationCards() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {QUALIFICATIONS.map((q) => (
        <NavCard
          key={q.slug}
          to={practicePath(q.slug)}
          title={q.name}
          description={q.description}
          meta={`${getBoards(q.slug).length} exam boards`}
          action="Get started"
          disabled={!isSupported({ qualification: q.slug })}
        />
      ))}
    </div>
  )
}
