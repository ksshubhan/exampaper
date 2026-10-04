import { Link } from 'react-router-dom'
import ComingSoonBadge from './ComingSoonBadge'

interface SubjectCardProps {
  to: string
  name: string
  /** Render inert, with a "Coming soon" badge under the name. */
  disabled?: boolean
}

export default function SubjectCard({
  to,
  name,
  disabled = false,
}: SubjectCardProps) {
  // A plain div: no link, no focus stop, no hover or active affordance.
  if (disabled) {
    return (
      <div
        aria-disabled="true"
        className="flex min-h-24 cursor-not-allowed flex-col items-center justify-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-center text-base font-medium text-[var(--text)] opacity-60 shadow-sm"
      >
        {name}
        <ComingSoonBadge />
      </div>
    )
  }

  return (
    <Link
      to={to}
      className="flex min-h-24 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-center text-base font-medium text-[var(--text)] shadow-sm transition hover:border-[var(--muted)] active:scale-[0.99]"
    >
      {name}
    </Link>
  )
}
