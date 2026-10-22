/** The product mark: an "H" whose crossbar carries a small flow arrow — Hevo's
 * initial, and the pipeline learners are being taught to support. */
export function Logo({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect width="24" height="24" rx="6" fill="var(--accent)" />
      <path
        d="M7.5 6.5v11M16.5 6.5v11M7.5 12h8.2M13.6 9.9l2.2 2.1-2.2 2.1"
        fill="none"
        stroke="#fff"
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
