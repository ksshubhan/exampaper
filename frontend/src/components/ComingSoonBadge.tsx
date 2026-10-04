/** Small muted pill marking a card or option we don't support yet. */
export default function ComingSoonBadge({
  className = '',
}: {
  className?: string
}) {
  return (
    <span
      className={
        'inline-flex w-fit shrink-0 items-center rounded-full border border-[var(--border)] bg-[var(--hover)] px-2.5 py-0.5 text-xs font-medium text-[var(--muted)] ' +
        className
      }
    >
      Coming soon
    </span>
  )
}
