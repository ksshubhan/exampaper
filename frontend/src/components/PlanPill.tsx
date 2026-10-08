import { Link } from 'react-router-dom'
import { useMe } from '../hooks/useMe'
import { planLabel } from '../lib/plan'
import { ChevronRightIcon } from './icons'

/**
 * Plan badge in the nav. Renders nothing until someone is signed in and
 * /api/me has answered, so a signed-out or offline header is unchanged.
 */
export default function PlanPill() {
  const me = useMe()

  if (!me) return null

  // The badge is also the way to the account page — plan, usage and billing
  // all live behind it. Phones get a short label so the header still fits;
  // the chevron is what makes it read as a link rather than a status chip.
  return (
    <Link
      to="/account"
      title={me.email}
      aria-label={`Account: ${planLabel(me)}`}
      className="flex items-center gap-1 whitespace-nowrap rounded-full border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--muted)] transition hover:bg-[var(--hover)] hover:text-[var(--text)]"
    >
      <span className="sm:hidden">{me.plan === 'monthly' ? 'Unlimited' : 'Free'}</span>
      <span className="hidden sm:inline">{planLabel(me)}</span>
      <ChevronRightIcon className="h-3.5 w-3.5 shrink-0" />
    </Link>
  )
}
