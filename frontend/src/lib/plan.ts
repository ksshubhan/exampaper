import type { Me } from './types'

/** The nav badge's wording for an account. */
export function planLabel(me: Me): string {
  if (me.plan === 'monthly') return 'Unlimited'
  return me.total_generations >= me.free_limit ? 'Free paper used' : '1 free paper'
}
