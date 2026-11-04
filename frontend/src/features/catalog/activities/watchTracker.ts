/** Works out *which stretches of a video were really played*, for the server
 * to verify. Pure and clock-free: it is fed observations (`observe`) and hands
 * back what has not been reported yet (`take`).
 *
 * A stretch only counts when the video was playing, at a speed the author
 * credits, and the position advanced the way playing would advance it. Any
 * jump — a seek forward or back — closes the current stretch and opens a new
 * one, so skipped sections are never claimed. The server re-checks all of it
 * against its own clock; this just keeps an honest player's claims clean. */

export type Range = [number, number]

export interface Sample {
  /** Seconds into the video. */
  position: number
  /** Playback speed (1 = normal). */
  rate: number
  playing: boolean
  /** The tab is in the background. */
  hidden: boolean
  /** Milliseconds, from any monotonic-enough clock. */
  now: number
}

export interface Pending {
  ranges: Range[]
  hidden_seconds: number
}

/** Same limits as the server: a heartbeat holds at most this many stretches,
 * each no longer than the longest it will accept. */
const MAX_RANGES = 20
const MAX_RANGE = 250
/** Shorter than this is a blip (a seek landing), not watching. */
const MIN_RANGE = 0.2
/** How far past "exactly in step with the clock" a forward step may be. */
const SLACK_SECONDS = 0.6
const SLACK_FACTOR = 1.25

export function mergeRanges(ranges: Range[]): Range[] {
  const sorted = [...ranges].sort((a, b) => a[0] - b[0])
  const out: Range[] = []
  for (const [start, end] of sorted) {
    const last = out[out.length - 1]
    if (last && start <= last[1]) last[1] = Math.max(last[1], end)
    else out.push([start, end])
  }
  return out
}

const round = (n: number) => Math.round(n * 1000) / 1000

export function createTracker(maxRate: number) {
  let last: Sample | null = null
  let open: Range | null = null
  let pending: Range[] = []
  let hidden = 0
  let tooFast = false

  function close() {
    if (open && open[1] - open[0] >= MIN_RANGE) pending = mergeRanges([...pending, open])
    open = null
  }

  return {
    observe(s: Sample) {
      if (!s.playing || !Number.isFinite(s.position)) {
        close()
        last = null
        return
      }
      tooFast = s.rate > maxRate + 0.05
      if (tooFast) {
        // Faster than the author credits: it plays, but earns nothing.
        close()
        last = null
        return
      }
      if (last === null) {
        last = s
        open = [s.position, s.position]
        return
      }
      const seconds = Math.max((s.now - last.now) / 1000, 0)
      const step = s.position - last.position
      const inStep = step >= -0.05 && step <= seconds * s.rate * SLACK_FACTOR + SLACK_SECONDS
      if (inStep && open) {
        open[1] = Math.max(open[1], s.position)
        if (s.hidden) hidden += seconds
      } else {
        close() // a seek: whatever lies between is not claimed
        open = [s.position, s.position]
      }
      last = s
    },

    /** Everything not yet reported (clears it). */
    take(): Pending {
      const ranges = [...pending]
      if (open && open[1] - open[0] >= MIN_RANGE) ranges.push([open[0], open[1]])
      if (open) open = [open[1], open[1]] // carry on from here next time
      pending = []
      const merged = mergeRanges(ranges).flatMap(([start, end]) => split(start, end))
      // Over the limit? Send the earliest now and keep the rest for next time.
      const sent = merged.slice(0, MAX_RANGES)
      pending = mergeRanges(merged.slice(MAX_RANGES))
      const seconds = hidden
      hidden = 0
      return { ranges: sent.map(([a, b]) => [round(a), round(b)] as Range), hidden_seconds: round(seconds) }
    },

    /** A heartbeat didn't get through: take its contents back. */
    restore(sent: Pending) {
      pending = mergeRanges([...pending, ...sent.ranges])
      hidden += sent.hidden_seconds
    },

    /** Is the player running faster than the credited speed right now? */
    get tooFast() {
      return tooFast
    },

    /** Has anything been played that isn't reported yet? */
    get dirty() {
      return pending.length > 0 || (open !== null && open[1] - open[0] >= MIN_RANGE)
    },
  }
}

function split(start: number, end: number): Range[] {
  const parts: Range[] = []
  for (let from = start; from < end; from += MAX_RANGE) parts.push([from, Math.min(from + MAX_RANGE, end)])
  return parts
}

export type Tracker = ReturnType<typeof createTracker>
