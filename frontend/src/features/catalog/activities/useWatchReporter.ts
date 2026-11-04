import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, type WatchBody, type WatchReply } from '../../../lib/api'
import type { PlayerAdapter } from './playerAdapter'
import { createTracker } from './watchTracker'

const OBSERVE_EVERY_MS = 500
const HEARTBEAT_EVERY_MS = 15_000
/** Pauses and seeks flush straight away, but never more often than this. */
const MIN_GAP_MS = 2_000

interface Options {
  /** False in an author's preview, or before progress is available: nothing is sent. */
  enabled: boolean
  adapter: PlayerAdapter | null
  maxRate: number
  /** An embedded player has no length the server knows, so it reports one. */
  reportDuration: boolean
  send: (body: WatchBody, keepalive: boolean) => Promise<WatchReply>
}

function newSession(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  // Older browsers: good enough to tell sessions apart.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

/** Watches a player and tells the server what it played: a heartbeat every
 * 15 s while playing, and straight away on pause, seek, hide or leaving the
 * page. The server decides what counts; this only reports honestly.
 *
 * Returns `flush` for the player's own events and whether the player is
 * running faster than the credited speed. A problem the learner should know
 * about (progress can no longer be recorded) comes back as `problem`. */
export function useWatchReporter({ enabled, adapter, maxRate, reportDuration, send }: Options) {
  const [tooFast, setTooFast] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const flushRef = useRef<(keepalive?: boolean) => void>(() => {})
  // The latest `send`, without restarting the session whenever its identity changes.
  const sendRef = useRef(send)
  useEffect(() => {
    sendRef.current = send
  }, [send])

  useEffect(() => {
    if (!enabled || !adapter) return
    const tracker = createTracker(maxRate)
    const session = newSession()
    let seq = 0
    let inFlight = false
    let again = false
    let stopped = false
    let lastFlush = 0
    // Where the server last heard we were; nothing to report until that changes.
    let lastSentPosition = adapter.position()
    let announced = false
    let trailing: ReturnType<typeof setTimeout> | undefined

    function observe() {
      tracker.observe({
        position: adapter!.position(),
        rate: adapter!.rate(),
        playing: adapter!.playing(),
        hidden: typeof document !== 'undefined' && document.hidden,
        now: Date.now(),
      })
      setTooFast((was) => (was === tracker.tooFast ? was : tracker.tooFast))
      // Say hello the moment playback starts, so the server's clock runs from
      // here and the first real heartbeat can be believed in full.
      if (!announced && adapter!.playing()) {
        announced = true
        void flush(false, true)
      }
    }

    async function flush(keepalive = false, announce = false) {
      if (stopped) return
      if (inFlight) {
        again = true
        return
      }
      observe()
      const pending = tracker.take()
      const position = adapter!.position()
      if (
        !announce &&
        pending.ranges.length === 0 &&
        pending.hidden_seconds === 0 &&
        Math.abs(position - lastSentPosition) < 1
      ) {
        return // nothing new to say
      }
      const body: WatchBody = {
        session_id: session,
        seq: seq++,
        ranges: pending.ranges,
        position: Math.max(position, 0),
        rate: Math.max(adapter!.rate() || 1, 0.05),
        hidden_seconds: pending.hidden_seconds,
      }
      if (reportDuration) {
        const length = adapter!.duration()
        if (length) body.duration = length
      }
      inFlight = true
      lastFlush = Date.now()
      try {
        await sendRef.current(body, keepalive)
        lastSentPosition = position
        setProblem(null)
      } catch (err) {
        const status = err instanceof ApiError ? err.status : 0
        if (status === 400) {
          // The server won't take this and never will: don't resend it forever.
        } else if (status === 403 || status === 404 || status === 409) {
          stopped = true
          setProblem(
            err instanceof Error && err.message
              ? err.message
              : 'Your progress can’t be recorded for this video.',
          )
        } else {
          tracker.restore(pending) // a hiccup: say it again next time
        }
      } finally {
        inFlight = false
        if (again && !stopped) {
          again = false
          void flush()
        }
      }
    }

    flushRef.current = (keepalive = false) => {
      if (keepalive) return void flush(true)
      const wait = MIN_GAP_MS - (Date.now() - lastFlush)
      if (wait <= 0) return void flush()
      clearTimeout(trailing)
      trailing = setTimeout(() => void flush(), wait)
    }

    const observing = setInterval(observe, OBSERVE_EVERY_MS)
    const beating = setInterval(() => void flush(), HEARTBEAT_EVERY_MS)
    const onVisibility = () => {
      observe()
      if (document.hidden) void flush(true)
    }
    const onLeave = () => void flush(true)
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pagehide', onLeave)

    return () => {
      clearInterval(observing)
      clearInterval(beating)
      clearTimeout(trailing)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pagehide', onLeave)
      void flush(true) // what was watched since the last heartbeat
      flushRef.current = () => {}
    }
  }, [enabled, adapter, maxRate, reportDuration])

  const flush = useCallback((keepalive = false) => flushRef.current(keepalive), [])
  return { flush, tooFast, problem }
}
