import type { ReactNode, SVGProps } from 'react'

const PATHS: Record<string, ReactNode> = {
  check: <path d="M4 8.5l3 3 5-6" />,
  chevronDown: <path d="M4 6.5l4 4 4-4" />,
  chevronRight: <path d="M6.5 4l4 4-4 4" />,
  arrowLeft: <path d="M13 8H3m4-4L3 8l4 4" />,
  arrowRight: <path d="M3 8h10m-4-4l4 4-4 4" />,
  search: (
    <>
      <circle cx="7" cy="7" r="4.25" />
      <path d="M10.5 10.5L14 14" />
    </>
  ),
  menu: <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" />,
  close: <path d="M4 4l8 8M12 4l-8 8" />,
  clock: (
    <>
      <circle cx="8" cy="8" r="5.75" />
      <path d="M8 4.75V8l2.25 1.5" />
    </>
  ),
  plus: <path d="M8 3v10M3 8h10" />,
  trash: (
    <>
      <path d="M3 4.5h10M6.5 4.5V3h3v1.5M5 4.5l.5 8.5h5l.5-8.5" />
    </>
  ),
  grip: (
    <>
      <circle cx="6" cy="4" r=".9" fill="currentColor" stroke="none" />
      <circle cx="10" cy="4" r=".9" fill="currentColor" stroke="none" />
      <circle cx="6" cy="8" r=".9" fill="currentColor" stroke="none" />
      <circle cx="10" cy="8" r=".9" fill="currentColor" stroke="none" />
      <circle cx="6" cy="12" r=".9" fill="currentColor" stroke="none" />
      <circle cx="10" cy="12" r=".9" fill="currentColor" stroke="none" />
    </>
  ),
  arrowUp: <path d="M8 13V3m-4 4l4-4 4 4" />,
  arrowDown: <path d="M8 3v10m-4-4l4 4 4-4" />,
  eye: (
    <>
      <path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" />
      <circle cx="8" cy="8" r="2" />
    </>
  ),
  upload: <path d="M8 11V2.5M4.5 6L8 2.5 11.5 6M3 13.5h10" />,
  // --- learning patterns ---
  bulb: (
    <>
      <path d="M6 12.5h4M6.75 14.25h2.5" />
      <path d="M8 1.75a4 4 0 0 0-2.2 7.35c.45.3.7.75.7 1.4h3c0-.65.25-1.1.7-1.4A4 4 0 0 0 8 1.75z" />
    </>
  ),
  target: (
    <>
      <circle cx="8" cy="8" r="5.75" />
      <circle cx="8" cy="8" r="2.5" />
    </>
  ),
  chat: <path d="M2.5 4.25A1.75 1.75 0 0 1 4.25 2.5h7.5a1.75 1.75 0 0 1 1.75 1.75v4.5a1.75 1.75 0 0 1-1.75 1.75H7L4 13.25V10.5h0a1.75 1.75 0 0 1-1.5-1.75z" />,
  alert: (
    <>
      <path d="M8 2.25l6 10.5H2z" />
      <path d="M8 6.5v2.75M8 11.1v.05" />
    </>
  ),
  bookmark: <path d="M4.5 2.5h7v11L8 10.5l-3.5 3z" />,
  // --- activity types ---
  book: (
    <>
      <path d="M3 3.5A1.5 1.5 0 0 1 4.5 2H13v10H4.5A1.5 1.5 0 0 0 3 13.5z" />
      <path d="M3 13.5A1.5 1.5 0 0 0 4.5 15H13" />
    </>
  ),
  play: <path d="M5.5 3.5v9l7-4.5z" />,
  quiz: (
    <>
      <circle cx="8" cy="8" r="5.75" />
      <path d="M6.5 6.4a1.5 1.5 0 1 1 2.2 1.3c-.5.3-.7.6-.7 1.2M8 11.1v.05" />
    </>
  ),
  tool: <path d="M10.5 2.5a3 3 0 0 0-2.8 4L2.8 11.4a1.2 1.2 0 0 0 1.7 1.7L9.4 8.2a3 3 0 0 0 4-2.8l-2 2-1.8-.5-.5-1.8z" />,
  external: <path d="M9 2.5h4.5V7M13.5 2.5l-6 6M12 9.5v3a1 1 0 0 1-1 1H3.5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h3" />,
  file: (
    <>
      <path d="M4 2h5l3 3v9H4z" />
      <path d="M9 2v3h3" />
    </>
  ),
}

export type IconName = keyof typeof PATHS

interface Props extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: IconName
  size?: number
}

/** Decorative by default (aria-hidden); pair with visible/sr-only text. */
export function Icon({ name, size = 16, ...rest }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  )
}
