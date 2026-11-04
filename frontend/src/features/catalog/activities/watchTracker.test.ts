import { describe, expect, it } from 'vitest'

import { createTracker, mergeRanges, type Sample } from './watchTracker'

/** Plays at 1× from `from`, one sample every `every` ms, for `seconds` of video. */
function play(
  tracker: ReturnType<typeof createTracker>,
  clock: { now: number },
  from: number,
  seconds: number,
  opts: Partial<Sample> & { every?: number } = {},
) {
  const every = opts.every ?? 500
  const rate = opts.rate ?? 1
  const steps = Math.round((seconds * 1000) / (every * rate))
  for (let i = 0; i <= steps; i++) {
    tracker.observe({
      position: from + (i * every * rate) / 1000,
      rate,
      playing: true,
      hidden: false,
      now: clock.now + i * every,
      ...opts,
    })
  }
  clock.now += steps * every
  return from + seconds
}

const pause = (t: ReturnType<typeof createTracker>, clock: { now: number }, position: number) =>
  t.observe({ position, rate: 1, playing: false, hidden: false, now: clock.now })

describe('watch tracker', () => {
  it('reports what was played, as one stretch', () => {
    const t = createTracker(1)
    const clock = { now: 0 }
    play(t, clock, 0, 15)
    expect(t.take().ranges).toEqual([[0, 15]])
  })

  it('a pause ends a stretch; playing again starts another', () => {
    const t = createTracker(1)
    const clock = { now: 0 }
    play(t, clock, 0, 10)
    pause(t, clock, 10)
    clock.now += 30_000 // a long break
    play(t, clock, 10, 5)
    expect(t.take().ranges).toEqual([[0, 15]]) // touching stretches join up
  })

  it('a forward seek is not claimed', () => {
    const t = createTracker(1)
    const clock = { now: 0 }
    play(t, clock, 0, 10)
    clock.now += 500
    play(t, clock, 60, 10) // jumped from 10 to 60
    expect(t.take().ranges).toEqual([
      [0, 10],
      [60, 70],
    ])
  })

  it('a backward seek opens a fresh stretch (and rewatching adds nothing new for the server)', () => {
    const t = createTracker(1)
    const clock = { now: 0 }
    play(t, clock, 30, 10)
    clock.now += 500
    play(t, clock, 5, 5)
    expect(t.take().ranges).toEqual([
      [5, 10],
      [30, 40],
    ])
  })

  it('scrubbing the bar through the video claims nothing', () => {
    const t = createTracker(1)
    const clock = { now: 0 }
    for (let p = 0; p <= 600; p += 20) {
      t.observe({ position: p, rate: 1, playing: true, hidden: false, now: clock.now })
      clock.now += 100
    }
    expect(t.take().ranges).toEqual([])
  })

  it('claims nothing while the speed is above the credited maximum', () => {
    const t = createTracker(1)
    const clock = { now: 0 }
    play(t, clock, 0, 20, { rate: 2 })
    expect(t.tooFast).toBe(true)
    expect(t.take().ranges).toEqual([])
    play(t, clock, 40, 10, { rate: 1 })
    expect(t.tooFast).toBe(false)
    expect(t.take().ranges).toEqual([[40, 50]])
  })

  it('credits a faster speed when the author allows it', () => {
    const t = createTracker(2)
    const clock = { now: 0 }
    play(t, clock, 0, 20, { rate: 2 })
    expect(t.take().ranges).toEqual([[0, 20]])
  })

  it('a hair over the speed is tolerated (rounding in the player)', () => {
    const t = createTracker(1)
    const clock = { now: 0 }
    play(t, clock, 0, 10, { rate: 1.04 })
    expect(t.take().ranges.length).toBe(1)
  })

  it('ignores blips shorter than a fraction of a second', () => {
    const t = createTracker(1)
    t.observe({ position: 10, rate: 1, playing: true, hidden: false, now: 0 })
    t.observe({ position: 10.1, rate: 1, playing: true, hidden: false, now: 100 })
    expect(t.take().ranges).toEqual([])
  })

  it('carries on from where it left off after taking a heartbeat', () => {
    const t = createTracker(1)
    const clock = { now: 0 }
    play(t, clock, 0, 15)
    expect(t.take().ranges).toEqual([[0, 15]])
    play(t, clock, 15, 15)
    expect(t.take().ranges).toEqual([[15, 30]])
  })

  it('counts background time without refusing the credit', () => {
    const t = createTracker(1)
    const clock = { now: 0 }
    play(t, clock, 0, 10, { hidden: true })
    const taken = t.take()
    expect(taken.ranges).toEqual([[0, 10]])
    expect(taken.hidden_seconds).toBeCloseTo(10, 0)
    expect(t.take().hidden_seconds).toBe(0)
  })

  it('a heartbeat that failed to send is put back, merged with what came after', () => {
    const t = createTracker(1)
    const clock = { now: 0 }
    play(t, clock, 0, 15)
    const failed = t.take()
    play(t, clock, 15, 15)
    t.restore(failed)
    expect(t.take().ranges).toEqual([[0, 30]])
  })

  it('never builds a stretch the server would refuse', () => {
    const t = createTracker(1)
    const clock = { now: 0 }
    play(t, clock, 0, 600, { every: 1000 })
    const { ranges } = t.take()
    expect(ranges.every(([a, b]) => b - a <= 250)).toBe(true)
    expect(ranges[0][0]).toBe(0)
    expect(ranges[ranges.length - 1][1]).toBe(600)
  })

  it('sends at most 20 stretches at a time and keeps the rest', () => {
    const t = createTracker(1)
    const clock = { now: 0 }
    for (let i = 0; i < 30; i++) {
      play(t, clock, i * 20, 5)
      clock.now += 500
    }
    const first = t.take()
    expect(first.ranges).toHaveLength(20)
    const second = t.take()
    expect(second.ranges).toHaveLength(10)
  })

  it('reports whether anything is waiting to be sent', () => {
    const t = createTracker(1)
    expect(t.dirty).toBe(false)
    const clock = { now: 0 }
    play(t, clock, 0, 5)
    expect(t.dirty).toBe(true)
    t.take()
    expect(t.dirty).toBe(false)
  })

  it('ignores a nonsense position', () => {
    const t = createTracker(1)
    t.observe({ position: Number.NaN, rate: 1, playing: true, hidden: false, now: 0 })
    expect(t.take().ranges).toEqual([])
  })
})

describe('mergeRanges', () => {
  it('joins overlapping and touching stretches', () => {
    expect(mergeRanges([[5, 8], [0, 3], [3, 4], [7, 10]])).toEqual([[0, 4], [5, 10]])
  })
})
