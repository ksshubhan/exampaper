import { Link } from 'react-router-dom'
import ComingSoonBadge from './ComingSoonBadge'

interface NavCardProps {
  to: string
  title: string
  description?: string
  meta?: string
  action: string
  /** Render inert, with a "Coming soon" badge in place of the action link. */
  disabled?: boolean
}

const CARD =
  'flex flex-col rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-sm'

/** Left-aligned info card: title, optional blurb, a meta line, and an action link. */
export default function NavCard({
  to,
  title,
  description,
  meta,
  action,
  disabled = false,
}: NavCardProps) {
  const heading = (
    <>
      <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
      {description && (
        <p className="mt-2 text-sm leading-relaxed text-[var(--muted)]">
          {description}
        </p>
      )}
    </>
  )

  // A plain div: no link, no focus stop, no hover or active affordance. The
  // meta line goes too — a board count means nothing until you can open it.
  if (disabled) {
    return (
      <div
        aria-disabled="true"
        className={CARD + ' cursor-not-allowed opacity-60'}
      >
        {heading}
        <ComingSoonBadge className="mt-4" />
      </div>
    )
  }

  return (
    <Link
      to={to}
      className={
        'group ' + CARD + ' transition hover:border-[var(--muted)] active:scale-[0.99]'
      }
    >
      {heading}
      {meta && <p className="mt-4 text-sm text-[var(--muted)]">{meta}</p>}
      <span className="mt-3 text-sm font-medium text-[var(--text)]">
        {action}{' '}
        <span
          aria-hidden
          className="inline-block transition-transform group-hover:translate-x-0.5"
        >
          →
        </span>
      </span>
    </Link>
  )
}
