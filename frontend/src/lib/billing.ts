/**
 * Plans, the price shown on screen, and what each backend error code says.
 *
 * The limits live on the backend; this module only decides the wording. Three
 * of these strings are fixed by `docs/accounts-and-payments.md` and are asserted
 * on by eye during the manual test — change them there first.
 */

import { ApiError } from './api'

/**
 * The monthly plan's price, as displayed. The one place to change it.
 *
 * It must match the Stripe price behind `STRIPE_PRICE_MONTHLY`: Checkout
 * charges whatever Stripe says, and nothing here can see that number, so a
 * price change in the dashboard means a change on this line too.
 */
export const PRICE_MONTHLY_DISPLAY = '£5'

/** What that price buys, in billing-period words. */
export const PRICE_MONTHLY_PERIOD = 'per month'

/** 429 `daily_limit_reached` — a monthly subscriber past the fair-use cap. */
export const DAILY_LIMIT_MESSAGE =
  "You've reached today's limit. It resets at midnight."

/**
 * Error codes that mean "come back tomorrow", both answered with
 * DAILY_LIMIT_MESSAGE: the fair-use cap, and the abuse ceiling on attempts
 * (`too_many_attempts`, 429). Both reset at Europe/London midnight, and
 * neither opens the upgrade popup — an upsell is the wrong answer to
 * suspected abuse, and the sentence is all a real parent needs either way.
 */
const DAILY_LIMIT_CODES = ['daily_limit_reached', 'too_many_attempts']

/**
 * The ways a download can be refused, and what each one says.
 *
 * None of them opens the upgrade popup. `too_many_renders` is the abuse
 * ceiling on rendering — an upsell is the wrong answer to it, and a
 * subscriber who meets it has nothing left to buy. The rest are either a
 * fault in one particular document or a queue, and no subscription fixes
 * either. The last two are the only ones worth retrying immediately.
 */
export const DOWNLOAD_LIMIT_MESSAGE =
  "You've reached today's download limit. It resets at midnight."
export const DOWNLOAD_TOO_LARGE_MESSAGE =
  'This paper is too big to turn into a PDF. Try generating a shorter one.'
export const DOWNLOAD_TIMEOUT_MESSAGE =
  'Building the PDF took too long. Please try the download again.'
export const DOWNLOAD_IN_PROGRESS_MESSAGE =
  'Another download is still running. Give it a moment.'
export const DOWNLOAD_BUSY_MESSAGE = 'Busy — try again in a moment.'

/** 503 `billing_unavailable` — Stripe is unreachable or misconfigured. */
export const BILLING_UNAVAILABLE_MESSAGE =
  "Payment isn't available right now. Please try again shortly."

/** True for the 402 that means "this account has used its free paper". */
export function isUpgradeRequired(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'upgrade_required'
}

/**
 * The inline message for a failed generation.
 *
 * `upgrade_required` never reaches here — it opens the popup instead, so a
 * caller checks `isUpgradeRequired` first.
 */
export function generationErrorMessage(
  error: unknown,
  fallback = 'Something went wrong.',
): string {
  if (error instanceof ApiError && DAILY_LIMIT_CODES.includes(error.code ?? '')) {
    return DAILY_LIMIT_MESSAGE
  }
  return error instanceof Error ? error.message : fallback
}

/**
 * The inline message for a failed PDF download.
 *
 * Shown next to the download button. Anything unrecognised falls through to
 * the error's own text, so a new backend code is still legible before this
 * list learns about it.
 */
export function downloadErrorMessage(
  error: unknown,
  fallback = 'Could not build the PDF.',
): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case 'too_many_renders':
        return DOWNLOAD_LIMIT_MESSAGE
      case 'render_too_large':
        return DOWNLOAD_TOO_LARGE_MESSAGE
      case 'render_timeout':
        return DOWNLOAD_TIMEOUT_MESSAGE
      case 'render_in_progress':
        return DOWNLOAD_IN_PROGRESS_MESSAGE
      case 'render_busy':
        return DOWNLOAD_BUSY_MESSAGE
    }
  }
  return error instanceof Error ? error.message : fallback
}

/** The inline message for a failed Checkout or Customer Portal call. */
export function billingErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case 'billing_unavailable':
        return BILLING_UNAVAILABLE_MESSAGE
      case 'already_subscribed':
        return "You're already subscribed."
      case 'no_customer':
        return 'There is no subscription to manage yet.'
      case 'auth_required':
        return 'Please sign in again.'
    }
  }
  return error instanceof Error
    ? error.message
    : 'Something went wrong. Please try again shortly.'
}
