import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useCheckout } from '../hooks/useCheckout'

/**
 * What a 402 `upgrade_required` looks like: the free paper is spent, and the
 * only way on is to subscribe.
 *
 * Mounted only while open — the parent renders it on the 402 — so "open" and
 * "mounted" are the same thing and the focus handling has no idle state.
 */

/** Tab order inside the dialog; also what gets focused on open. */
const FOCUSABLE =
  'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])'

interface UpgradeModalProps {
  onClose: () => void
}

export default function UpgradeModal({ onClose }: UpgradeModalProps) {
  const dialog = useRef<HTMLDivElement>(null)
  const { start, busy, error } = useCheckout()

  // Focus moves into the dialog, and back to whatever opened it on close —
  // otherwise a keyboard user lands at the top of the document.
  useEffect(() => {
    const opener = document.activeElement
    dialog.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    return () => {
      if (opener instanceof HTMLElement) opener.focus()
    }
  }, [])

  // The page behind must not scroll under the overlay.
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  // Escape closes, and Tab cycles within the dialog rather than walking off
  // into the page behind it. Captured, so it runs before anything else.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const nodes = Array.from(
        dialog.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [],
      )
      if (nodes.length === 0) return
      const first = nodes[0]
      const last = nodes[nodes.length - 1]
      const active = document.activeElement
      const outside = !dialog.current?.contains(active)
      if (event.shiftKey ? active === first || outside : active === last) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      }
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [onClose])

  return (
    <div className="no-print fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="upgrade-modal-title"
        className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4">
          <h2
            id="upgrade-modal-title"
            className="text-lg font-semibold tracking-tight"
          >
            You've used your free paper
          </h2>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="-mr-1 -mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[var(--muted)] transition hover:bg-[var(--hover)] hover:text-[var(--text)]"
          >
            <span aria-hidden className="text-xl leading-none">
              &times;
            </span>
          </button>
        </div>

        <p className="mt-3 text-sm text-[var(--muted)]">
          The paid plan gives you unlimited papers and worksheets, every one
          with its mark scheme.
        </p>

        <button
          type="button"
          onClick={start}
          disabled={busy}
          className="mt-5 w-full rounded-xl bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-[var(--accent-text)] transition hover:opacity-90 disabled:opacity-50"
        >
          {busy ? 'Opening payment…' : 'Continue to payment'}
        </button>

        {error && (
          <p role="alert" className="mt-2 text-sm text-red-500">
            {error}
          </p>
        )}

        <div className="mt-4 flex items-center justify-between gap-3">
          <Link
            to="/pricing"
            onClick={onClose}
            className="text-sm font-medium text-[var(--text)] underline decoration-[var(--border)] underline-offset-4 transition hover:decoration-[var(--text)]"
          >
            See all plans
          </Link>
          <span className="text-xs text-[var(--muted)]">
            Secure payment by Stripe
          </span>
        </div>
      </div>
    </div>
  )
}
