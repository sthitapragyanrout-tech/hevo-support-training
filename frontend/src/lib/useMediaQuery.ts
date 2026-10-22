import { useEffect, useState } from 'react'

/** Tracks a CSS media query. Falls back to `false` where matchMedia is
 * unavailable (jsdom), i.e. tests render the desktop layout by default. */
export function useMediaQuery(query: string): boolean {
  const get = () => (typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : false)
  const [matches, setMatches] = useState(get)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    onChange()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])

  return matches
}
