import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, simApi, type SimSession, type SkipReason } from '../../../lib/api'

const POLL_WAITING_MS = 2000
const POLL_QUIET_MS = 20_000

const isOver = (s: SimSession) => s.state === 'finished' || s.state === 'abandoned'

/** One practice ticket as the learner sees it: the thread, sending a reply,
 * and keeping up with the customer. Polls quickly while we're waiting on the
 * customer (or on feedback) and slowly otherwise — so a nudge or a timeout shows
 * up without hammering the server. The same reply is only ever accepted once
 * (it carries an id), so a retry after a dropped connection is safe. */
export function useTicketSession(initial: SimSession, onSettled?: (s: SimSession) => void) {
  const [session, setSession] = useState(initial)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Bumped after every look at the ticket, so the next look is always scheduled.
  const [looks, setLooks] = useState(0)
  const pendingReply = useRef<{ text: string; id: string } | null>(null)
  const settled = useRef(onSettled)
  useEffect(() => {
    settled.current = onSettled
  })

  const over = isOver(session)
  useEffect(() => {
    if (over) return
    const waiting = session.waiting_for_customer || session.feedback_pending
    const timer = setTimeout(
      async () => {
        try {
          setSession(await simApi.get(session.id))
        } catch {
          // a hiccup: the next poll tries again
        }
        setLooks((n) => n + 1)
      },
      waiting ? POLL_WAITING_MS : POLL_QUIET_MS,
    )
    return () => clearTimeout(timer)
  }, [session, over, looks])

  const state = session.state
  useEffect(() => {
    if (state === 'finished' || state === 'abandoned') settled.current?.(session)
    // Tell the page once per change of outcome, not on every poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state])

  const run = useCallback(async (task: () => Promise<SimSession>, fallback: string) => {
    setBusy(true)
    setProblem(null)
    try {
      setSession(await task())
      return true
    } catch (err) {
      setProblem(err instanceof ApiError && err.message ? err.message : fallback)
      if (err instanceof ApiError && err.status === 409) {
        // The ticket moved on (ended, or answered) — show it as it is now.
        simApi.get(session.id).then(setSession, () => {})
      }
      return false
    } finally {
      setBusy(false)
    }
  }, [session.id])

  const send = useCallback(
    (text: string) => {
      const same = pendingReply.current?.text === text
      const id = same && pendingReply.current ? pendingReply.current.id : crypto.randomUUID()
      pendingReply.current = { text, id }
      return run(async () => {
        const next = await simApi.send(session.id, text, id)
        pendingReply.current = null
        return next
      }, 'Your reply couldn’t be sent. Check your connection and try again.')
    },
    [run, session.id],
  )

  return {
    session,
    problem,
    busy,
    over,
    send,
    retry: () => run(() => simApi.retry(session.id), 'We couldn’t try again just now.'),
    finish: () => run(() => simApi.finish(session.id), 'We couldn’t finish the ticket just now.'),
    skip: (reason: SkipReason) =>
      run(() => simApi.skip(session.id, reason), 'We couldn’t skip this question just now.'),
  }
}
