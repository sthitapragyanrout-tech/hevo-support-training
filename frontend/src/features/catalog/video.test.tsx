import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type ActivitySummary, type WatchBody, type WatchReply } from '../../lib/api'
import { VideoActivity } from './activities/VideoActivity'
import type { CourseContext } from './courseContext'
import { INERT_PROGRESS, type Progress } from './useProgress'

// -- a stand-in for the browser's media element ------------------------------

const media = { position: 0, playing: false, rate: 1, length: 120 }
const originals: Record<string, PropertyDescriptor | undefined> = {}
const patched: Record<string, PropertyDescriptor> = {
  currentTime: { get: () => media.position, set: (v: number) => void (media.position = v), configurable: true },
  paused: { get: () => !media.playing, configurable: true },
  ended: { get: () => false, configurable: true },
  readyState: { get: () => 4, configurable: true },
  playbackRate: { get: () => media.rate, set: (v: number) => void (media.rate = v), configurable: true },
  duration: { get: () => media.length, configurable: true },
}

beforeEach(() => {
  vi.useFakeTimers()
  Object.assign(media, { position: 0, playing: false, rate: 1, length: 120 })
  for (const [name, descriptor] of Object.entries(patched)) {
    originals[name] = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, name)
    Object.defineProperty(HTMLMediaElement.prototype, name, descriptor)
  }
  HTMLMediaElement.prototype.play = vi.fn(async () => {
    media.playing = true
  })
  HTMLMediaElement.prototype.pause = vi.fn(() => {
    media.playing = false
  })
})

afterEach(() => {
  vi.useRealTimers()
  for (const [name, original] of Object.entries(originals)) {
    if (original) Object.defineProperty(HTMLMediaElement.prototype, name, original)
    else delete (HTMLMediaElement.prototype as unknown as Record<string, unknown>)[name]
  }
})

/** The video plays for `seconds` of real time, in half-second ticks. */
async function playFor(seconds: number) {
  for (let i = 0; i < seconds * 2; i++) {
    if (media.playing) media.position += 0.5 * media.rate
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500)
    })
  }
}

// -- a course context with a controllable progress ---------------------------

const UPLOAD: ActivitySummary = {
  id: 3,
  activity_type: 'video',
  title: 'Ingestion walkthrough',
  is_required: true,
  points: 0,
  order: 0,
  max_attempts: 3,
  completable: true,
  config: {
    source: 'upload',
    media_asset: 9,
    media_url: '/api/v1/media/9/video/',
    poster_url: '/api/v1/media/9/poster/',
    duration: 120,
    completion_threshold: 0.9,
    max_credited_rate: 1,
  },
}

const REPLY: WatchReply = {
  state: null,
  completed: false,
  watched_fraction: 0.125,
  needed_fraction: 0.9,
  position: 15,
  duration: 120,
  accepted_seconds: 15,
}

function setup(
  options: {
    activity?: ActivitySummary
    preview?: boolean
    state?: 'completed'
    watch?: { watched_fraction: number; position: number }
    send?: (body: WatchBody) => Promise<WatchReply>
  } = {},
) {
  const sent: { body: WatchBody; keepalive: boolean }[] = []
  const progress: Progress = {
    ...INERT_PROGRESS,
    available: true,
    activities: options.state ? { 3: options.state } : {},
    watch: options.watch ? { 3: options.watch } : {},
    startActivity: vi.fn(async () => {}),
    completeActivity: vi.fn(async () => {}),
    uncompleteActivity: vi.fn(async () => {}),
    sendWatch: vi.fn(async (_id, body, keepalive = false) => {
      sent.push({ body, keepalive })
      return options.send ? options.send(body) : REPLY
    }),
  }
  const context = { preview: options.preview ?? false, progress } as unknown as CourseContext
  render(
    <MemoryRouter>
      <Routes>
        <Route element={<Outlet context={context} />}>
          <Route index element={<VideoActivity activity={options.activity ?? UPLOAD} />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
  return { progress, sent }
}

const startPlaying = async () => {
  fireEvent.click(screen.getByRole('button', { name: /Watch|Resume/ }))
  const video = document.querySelector('video') as HTMLVideoElement
  fireEvent.loadedMetadata(video)
  await act(async () => {})
  return video
}

describe('Video activity — playing in place', () => {
  it('opens the video inside the lesson: no link, no new tab', async () => {
    const open = vi.spyOn(window, 'open')
    setup()
    expect(screen.getByText('Ingestion walkthrough')).toBeInTheDocument()
    expect(screen.getByText(/Video · 2 min · Required/)).toBeInTheDocument()
    expect(document.querySelector('video')).toBeNull()

    const video = await startPlaying()
    expect(video).toHaveAttribute('src', '/api/v1/media/9/video/')
    expect(video).toHaveAttribute('poster', '/api/v1/media/9/poster/')
    expect(video.controls).toBe(true)
    expect(screen.getByRole('button', { name: 'Hide video' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(open).not.toHaveBeenCalled()
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled()
  })

  it('states a short clip’s length in seconds, not as "1 min"', () => {
    setup({ activity: { ...UPLOAD, config: { ...UPLOAD.config, duration: 30 } } })
    expect(screen.getByText(/Video · 30 sec · Required/)).toBeInTheDocument()
  })

  it('hides the video again, removing the player', async () => {
    setup()
    await startPlaying()
    fireEvent.click(screen.getByRole('button', { name: 'Hide video' }))
    expect(document.querySelector('video')).toBeNull()
  })

  it('records that it was started', async () => {
    const { progress } = setup()
    await startPlaying()
    expect(progress.startActivity).toHaveBeenCalledWith(3)
  })

  it('shows a video with nothing behind it as "Available soon", in the same frame', () => {
    setup({ activity: { ...UPLOAD, completable: false, config: { source: 'upload', completion_threshold: 0.9 } } })
    expect(screen.getByText('Available soon')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Watch/ })).not.toBeInTheDocument()
  })

  it('says plainly when the file cannot be loaded', async () => {
    setup()
    const video = await startPlaying()
    fireEvent.error(video)
    expect(screen.getByRole('alert')).toHaveTextContent(/couldn’t be loaded/)
  })
})

describe('Video activity — reporting what was watched', () => {
  it('says hello the moment playback starts, with nothing claimed yet', async () => {
    const { sent } = setup()
    await startPlaying()
    expect(sent).toHaveLength(0) // not playing until the browser says so
    await playFor(1)
    expect(sent).toHaveLength(1)
    expect(sent[0].body).toMatchObject({ seq: 0, ranges: [], hidden_seconds: 0 })
    expect(sent[0].body.session_id).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('does not say hello for a video that was opened but never played', async () => {
    HTMLMediaElement.prototype.play = vi.fn(async () => {}) // the browser refuses to start it
    const { sent } = setup()
    await startPlaying()
    await playFor(20)
    expect(sent).toHaveLength(0)
  })

  it('sends a heartbeat every 15 seconds with the stretch that was played', async () => {
    const { sent } = setup()
    await startPlaying()
    await playFor(16)
    const real = sent.filter((s) => s.body.ranges.length > 0)
    expect(real).toHaveLength(1)
    const { body, keepalive } = real[0]
    expect(keepalive).toBe(false)
    expect(body.seq).toBe(1) // seq 0 was the hello
    expect(body.session_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(body.ranges).toHaveLength(1)
    expect(body.ranges[0][0]).toBeLessThan(1) // the first half-second may be missed
    expect(body.ranges[0][1]).toBeGreaterThan(13)
    expect(body.rate).toBe(1)
    await playFor(15)
    const all = sent.filter((s) => s.body.ranges.length > 0)
    expect(all[1].body.seq).toBe(2)
    expect(all[1].body.session_id).toBe(body.session_id)
  })

  it('reports straight away on pause (but not in a flurry)', async () => {
    const { sent } = setup()
    const video = await startPlaying()
    await playFor(5)
    media.playing = false
    fireEvent.pause(video)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500)
    })
    const real = sent.filter((s) => s.body.ranges.length > 0)
    expect(real.length).toBeGreaterThanOrEqual(1)
    expect(real[0].body.ranges[0][1]).toBeGreaterThan(3)
  })

  it('does not claim a skipped section', async () => {
    const { sent } = setup()
    const video = await startPlaying()
    await playFor(5)
    media.position = 90 // dragged the bar
    fireEvent.seeked(video)
    await playFor(5)
    await playFor(6)
    const claimed = sent.flatMap((s) => s.body.ranges)
    expect(claimed.every(([a, b]) => b <= 10 || a >= 90)).toBe(true)
    expect(claimed.some(([a, b]) => a < 80 && b > 20)).toBe(false)
  })

  it('shows real progress once something has been watched', async () => {
    setup({ watch: { watched_fraction: 0.625, position: 75 } })
    expect(screen.getByText(/Resume from 1:15/)).toBeInTheDocument()
    await startPlaying()
    expect(screen.getByRole('status')).toHaveTextContent('Watched 63% · 90% needed')
  })

  it('shows no percentage before anything has been watched', async () => {
    setup()
    await startPlaying()
    expect(screen.getByRole('status')).not.toHaveTextContent(/%/)
  })

  it('resumes where the learner stopped', async () => {
    setup({ watch: { watched_fraction: 0.4, position: 50 } })
    expect(screen.getByRole('button', { name: /Resume/ })).toBeInTheDocument()
    await startPlaying()
    expect(media.position).toBe(50)
  })

  it('does not resume from the first few seconds', async () => {
    setup({ watch: { watched_fraction: 0.02, position: 3 } })
    expect(screen.queryByText(/Resume from/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Watch/ })).toBeInTheDocument()
  })

  it('says speeding up is not counted — and sends nothing for that time', async () => {
    const { sent } = setup()
    const video = await startPlaying()
    media.rate = 2
    fireEvent.rateChange(video)
    await playFor(16)
    expect(screen.getByRole('status')).toHaveTextContent('Playing faster than 1× isn’t counted')
    expect(sent.flatMap((s) => s.body.ranges)).toEqual([])
    media.rate = 1
    fireEvent.rateChange(video)
    await playFor(2)
    expect(screen.getByRole('status')).not.toHaveTextContent(/faster/)
  })

  it('a heartbeat that fails to arrive is sent again with the next one', async () => {
    let fail = true
    const { sent } = setup({
      send: async () => {
        if (fail) throw new Error('network down')
        return REPLY
      },
    })
    await startPlaying()
    await playFor(16)
    fail = false
    await playFor(15)
    const last = sent[sent.length - 1].body
    expect(last.ranges[0][0]).toBeLessThan(1) // the first stretch came along too
    expect(last.ranges[0][1]).toBeGreaterThan(28)
  })

  it('stops quietly and says why when the server will not record it', async () => {
    const { sent } = setup({
      send: async () => {
        throw new ApiError(409, 'Finish “Pipelines” first.')
      },
    })
    await startPlaying()
    await playFor(16)
    expect(screen.getByRole('alert')).toHaveTextContent('Finish “Pipelines” first.')
    const count = sent.length
    await playFor(32)
    expect(sent.length).toBe(count) // no hammering a door that is shut
  })

  it('sends what was watched when the learner leaves', async () => {
    const { sent } = setup()
    await startPlaying()
    await playFor(6)
    act(() => {
      window.dispatchEvent(new Event('pagehide'))
    })
    await act(async () => {})
    expect(sent.at(-1)?.keepalive).toBe(true)
    expect(sent.at(-1)?.body.ranges[0][1]).toBeGreaterThan(4)
  })

  it('sends what was watched when the video is hidden or the page closes', async () => {
    const { sent } = setup()
    const video = await startPlaying()
    await playFor(6)
    fireEvent.click(screen.getByRole('button', { name: 'Hide video' }))
    await act(async () => {})
    expect(video).not.toBeInTheDocument()
    expect(sent.at(-1)?.keepalive).toBe(true)
  })

  it('stops reporting once the video is complete', async () => {
    const { sent } = setup({ state: 'completed' })
    expect(screen.getByText(/Video · 2 min · Watched · Required/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Watch again' }))
    await playFor(20)
    expect(sent).toHaveLength(0)
    expect(screen.getByRole('status')).toHaveTextContent('You’ve watched this video.')
  })
})

describe('Video activity — in an author’s preview', () => {
  it('plays, but records nothing and says so', async () => {
    const { sent, progress } = setup({ preview: true })
    await startPlaying()
    await playFor(20)
    expect(sent).toHaveLength(0)
    expect(progress.startActivity).not.toHaveBeenCalled()
    expect(screen.getByRole('status')).toHaveTextContent('Playing in preview — your viewing isn’t recorded.')
  })
})

describe('Video activity — YouTube', () => {
  const YT: ActivitySummary = {
    ...UPLOAD,
    config: {
      source: 'youtube',
      youtube_id: 'dQw4w9WgXcQ',
      completion_threshold: 0.9,
      max_credited_rate: 1,
    },
  }

  interface PlayerOptions {
    videoId: string
    host?: string
    playerVars?: Record<string, number>
    events?: { onReady?: () => void; onStateChange?: () => void }
  }

  class FakePlayer {
    static last: FakePlayer
    state = 2
    time = 0
    element: HTMLElement
    options: PlayerOptions
    constructor(element: HTMLElement, options: PlayerOptions) {
      this.element = element
      this.options = options
      FakePlayer.last = this
      element.setAttribute('data-fake-youtube', options.videoId)
      queueMicrotask(() => options.events?.onReady?.())
    }
    getCurrentTime = () => this.time
    getPlaybackRate = () => 1
    getPlayerState = () => this.state
    getDuration = () => 200
    seekTo = vi.fn()
    destroy = vi.fn()
  }

  beforeEach(() => {
    ;(window as unknown as { YT: unknown }).YT = { Player: FakePlayer }
  })
  afterEach(() => {
    delete (window as unknown as { YT?: unknown }).YT
  })

  it('plays in the lesson with YouTube’s own player (privacy-friendly host)', async () => {
    setup({ activity: YT })
    fireEvent.click(screen.getByRole('button', { name: /Watch/ }))
    await act(async () => {})
    expect(FakePlayer.last.options.videoId).toBe('dQw4w9WgXcQ')
    expect(FakePlayer.last.options.host).toBe('https://www.youtube-nocookie.com')
    expect(document.querySelector('[data-fake-youtube="dQw4w9WgXcQ"]')).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('tracks its position and reports the length it knows', async () => {
    const { sent } = setup({ activity: YT })
    fireEvent.click(screen.getByRole('button', { name: /Watch/ }))
    await act(async () => {})
    FakePlayer.last.state = 1 // playing
    for (let i = 0; i < 32; i++) {
      FakePlayer.last.time += 0.5
      await act(async () => {
        await vi.advanceTimersByTimeAsync(500)
      })
    }
    expect(sent[0].body).toMatchObject({ ranges: [], duration: 200 }) // the hello carries the length
    const real = sent.filter((s) => s.body.ranges.length > 0)
    expect(real.length).toBeGreaterThanOrEqual(1)
    expect(real[0].body.duration).toBe(200)
    expect(real[0].body.ranges[0][1]).toBeGreaterThan(13)
  })

  it('tears the player down when hidden', async () => {
    setup({ activity: YT })
    fireEvent.click(screen.getByRole('button', { name: /Watch/ }))
    await act(async () => {})
    const player = FakePlayer.last
    fireEvent.click(screen.getByRole('button', { name: 'Hide video' }))
    expect(player.destroy).toHaveBeenCalled()
  })
})


describe('Video activity — Google Drive', () => {
  const DRIVE: ActivitySummary = {
    ...UPLOAD,
    config: {
      source: 'drive',
      drive_id: '1AbCdEfGhIjKlMnOpQrStUvWx',
      completion_threshold: 0.9,
      max_credited_rate: 1,
    },
  }

  it('plays in the lesson in Drive’s own preview — no link, no new tab', async () => {
    const open = vi.spyOn(window, 'open')
    setup({ activity: DRIVE })
    fireEvent.click(screen.getByRole('button', { name: /Watch/ }))
    const frame = screen.getByTitle('Ingestion walkthrough')
    expect(frame.tagName).toBe('IFRAME')
    expect(frame).toHaveAttribute(
      'src',
      'https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWx/preview',
    )
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(open).not.toHaveBeenCalled()
  })

  it('sends no watch heartbeats — there is nothing to measure — but records the start', async () => {
    const { sent, progress } = setup({ activity: DRIVE })
    fireEvent.click(screen.getByRole('button', { name: /Watch/ }))
    await playFor(40)
    expect(sent).toHaveLength(0)
    expect(progress.startActivity).toHaveBeenCalledWith(3)
  })

  it('is finished when the learner says so, and can be taken back', async () => {
    const { progress } = setup({ activity: DRIVE })
    fireEvent.click(screen.getByRole('button', { name: 'I’ve watched this' }))
    await act(async () => {})
    expect(progress.completeActivity).toHaveBeenCalledWith(3)
  })

  it('offers "Mark as unwatched" once confirmed', async () => {
    const { progress } = setup({ activity: DRIVE, state: 'completed' })
    expect(screen.getByText('Watched')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Mark as unwatched' }))
    await act(async () => {})
    expect(progress.uncompleteActivity).toHaveBeenCalledWith(3)
  })

  it('cannot be confirmed in an author’s preview', () => {
    setup({ activity: DRIVE, preview: true })
    expect(screen.getByRole('button', { name: 'I’ve watched this' })).toBeDisabled()
  })

  it('an uploaded video has no "I’ve watched this" shortcut', () => {
    setup()
    expect(screen.queryByRole('button', { name: 'I’ve watched this' })).not.toBeInTheDocument()
  })
})
