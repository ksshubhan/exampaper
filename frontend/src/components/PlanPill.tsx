import { Link } from 'react-router-dom'
import { useMe } from '../hooks/useMe'
import { planLabel } from '../lib/plan'

/**
 * Plan badge in the nav. Renders nothing until someone is signed in and
 * /api/me has answered, so a signed-out or offline header is unchanged.
 */
export default function PlanPill() {
  const me = useMe()

  if (!me) return null

  // The badge is also the way to the account page — plan, usage and billing
  // all live behind it.
  return (
    <Link
      to="/account"
      title={me.email}
      className="hidden whitespace-nowrap rounded-full border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--muted)] transition hover:bg-[var(--hover)] hover:text-[var(--text)] sm:inline-block"
    >
      {planLabel(me)}
    </Link>
  )
}
