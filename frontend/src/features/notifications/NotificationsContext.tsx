import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { notificationsApi } from '../../lib/api'

/** How often the unread count is refreshed while the tab is visible. */
export const POLL_MS = 60_000

interface Value {
  /** Unread notifications for the signed-in person. */
  unread: number
  /** Re-read the count from the server now. */
  refresh: () => Promise<void>
  /** Set it from a response that already carries the new count. */
  setUnread: (n: number) => void
}

const Ctx = createContext<Value>({ unread: 0, refresh: async () => {}, setUnread: () => {} })

export const useNotificationCount = () => useContext(Ctx)

/** Keeps the unread count fresh for the whole app shell: once on mount, once a minute while the
 * tab is visible, and again when the window regains focus. A failed poll is silent: the count just
 * stays as it was, and nothing on the page is ever blocked by it. No websockets. */
export function NotificationsProvider({
  enabled,
  children,
}: {
  enabled: boolean
  children: ReactNode
}) {
  const [unread, setUnread] = useState(0)

  const refresh = useCallback(async () => {
    try {
      setUnread((await notificationsApi.unreadCount()).unread_count)
    } catch {
      // Silent on purpose: a bell that can't reach the server shows what it last knew.
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    void refresh()
    const tick = () => {
      if (document.visibilityState === 'visible') void refresh()
    }
    const timer = window.setInterval(tick, POLL_MS)
    window.addEventListener('focus', tick)
    document.addEventListener('visibilitychange', tick)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', tick)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [enabled, refresh])

  const value = useMemo(() => ({ unread, refresh, setUnread }), [unread, refresh])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
