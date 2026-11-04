import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { VideoEditor } from './VideoEditor'
import type { AuthActivity } from './types'
import type { MediaAsset } from './studioApi'

const LIMITS = { max_upload_mb: 1024, max_duration_minutes: 120, allowed_extensions: ['mp4', 'mov', 'webm'] }

function asset(over: Partial<MediaAsset> = {}): MediaAsset {
  return {
    id: 5,
    status: 'processing',
    status_label: 'Processing',
    original_name: 'intro.mp4',
    size_bytes: 1000,
    duration_seconds: null,
    width: null,
    height: null,
    error: '',
    retryable: false,
    video_url: null,
    poster_url: null,
    ...over,
  }
}

const READY = asset({
  status: 'ready',
  status_label: 'Ready',
  duration_seconds: 125,
  video_url: '/api/v1/media/5/video/',
  poster_url: '/api/v1/media/5/poster/',
})

function activity(config: Record<string, unknown> = {}): AuthActivity {
  return {
    id: 11,
    activity_type: 'video',
    title: 'Intro video',
    config: { source: 'upload', ...config },
    is_required: true,
    points: 0,
    max_attempts: 3,
    mastery_threshold: null,
    order: 0,
    needs_setup: true,
    completable: false,
  }
}

// -- a fake XHR the test drives by hand ---------------------------------------

class FakeXhr {
  static last: FakeXhr
  upload: { onprogress?: (e: { lengthComputable: boolean; loaded: number; total: number }) => void } = {}
  onload?: () => void
  onerror?: () => void
  status = 0
  responseText = ''
  headers: Record<string, string> = {}
  method = ''
  url = ''
  body: FormData | null = null
  constructor() {
    FakeXhr.last = this
  }
  open(method: string, url: string) {
    this.method = method
    this.url = url
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value
  }
  send(body: FormData) {
    this.body = body
  }
  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total })
  }
  finish(status: number, body: unknown) {
    this.status = status
    this.responseText = JSON.stringify(body)
    this.onload?.()
  }
}

type Reply = { status: number; body: unknown }
let routes: Record<string, () => Reply>
let calls: { method: string; path: string }[]

function useRoutes(table: Record<string, () => Reply>) {
  routes = { 'GET /api/v1/authoring/media/limits/': () => ({ status: 200, body: LIMITS }), ...table }
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  calls = []
  routes = {}
  vi.stubGlobal('XMLHttpRequest', FakeXhr)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = (init.method ?? 'GET').toUpperCase()
      const path = url.split('?')[0]
      calls.push({ method, path })
      const handler = routes[`${method} ${path}`]
      const { status, body } = handler ? handler() : { status: 404, body: { detail: 'Not found.' } }
      return { ok: status < 300, status, statusText: 'x', json: async () => body }
    }),
  )
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function mount(config: Record<string, unknown> = {}, options: { disabled?: boolean } = {}) {
  const save = vi.fn(async () => {})
  const view = render(
    <VideoEditor activity={activity(config)} disabled={options.disabled ?? false} save={save} />,
  )
  // The Studio re-renders the editor with the saved config after each save.
  const saved = (next: Record<string, unknown>) =>
    view.rerender(<VideoEditor activity={activity(next)} disabled={false} save={save} />)
  return { save, saved }
}

const lastSaved = (save: ReturnType<typeof vi.fn>) => {
  const call = save.mock.calls[save.mock.calls.length - 1] as [{ config: Record<string, unknown> }]
  return call[0].config
}

const choose = (name = 'intro.mp4', size = 5000) => {
  const file = new File([new Uint8Array(1)], name, { type: 'video/mp4' })
  Object.defineProperty(file, 'size', { value: size })
  fireEvent.change(screen.getByLabelText('Choose a video file'), { target: { files: [file] } })
}

describe('Video editor — uploading', () => {
  it('offers a file picker and says what is allowed', async () => {
    useRoutes({})
    mount()
    expect(await screen.findByRole('button', { name: 'Choose a video' })).toBeInTheDocument()
    expect(await screen.findByText(/MP4, MOV, WEBM · up to 1024 MB and 2 hours/)).toBeInTheDocument()
  })

  it('shows real progress, then processing, then the ready video — played in the editor', async () => {
    useRoutes({ 'GET /api/v1/authoring/media/5/': () => ({ status: 200, body: asset() }) })
    const { save, saved } = mount()
    await screen.findByText(/up to 1024 MB/)
    choose()

    expect(screen.getByRole('status')).toHaveTextContent('Uploading intro.mp4… 0%')
    expect(FakeXhr.last.method).toBe('POST')
    expect(FakeXhr.last.url).toBe('/api/v1/authoring/media/')
    expect((FakeXhr.last.body as FormData).get('file')).toBeInstanceOf(File)
    act(() => FakeXhr.last.progress(2500, 5000))
    expect(screen.getByRole('status')).toHaveTextContent('50%')
    expect(screen.getByRole('progressbar', { name: 'Upload progress' })).toHaveValue(0.5)

    await act(async () => FakeXhr.last.finish(201, asset()))
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastSaved(save)).toMatchObject({ source: 'upload', media_asset: 5 })

    // The attached video is shown as processing, with reassurance.
    saved({ source: 'upload', media_asset: 5 })
    expect(await screen.findByText(/Processing/)).toBeInTheDocument()
    expect(screen.getByText(/You can leave this page/)).toBeInTheDocument()
  })

  it('keeps checking until the video is ready, then shows it with its length', async () => {
    let status: MediaAsset = asset()
    useRoutes({ 'GET /api/v1/authoring/media/5/': () => ({ status: 200, body: status }) })
    mount({ media_asset: 5 })
    expect(await screen.findByText(/Processing/)).toBeInTheDocument()

    status = READY
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100)
    })
    expect(await screen.findByText(/Ready · 2:05/)).toBeInTheDocument()
    const preview = screen.getByLabelText('Preview of the uploaded video')
    expect(preview).toHaveAttribute('src', '/api/v1/media/5/video/')
    expect(preview).toHaveAttribute('poster', '/api/v1/media/5/poster/')
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Replace video' })).toBeInTheDocument()
    // …and it stops asking.
    const asked = calls.filter((c) => c.path === '/api/v1/authoring/media/5/').length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(calls.filter((c) => c.path === '/api/v1/authoring/media/5/').length).toBe(asked)
  })

  it('tells the builder when processing finishes, so "Needs setup" clears', async () => {
    let current: MediaAsset = asset()
    useRoutes({ 'GET /api/v1/authoring/media/5/': () => ({ status: 200, body: current }) })
    const refresh = vi.fn(async () => {})
    render(
      <VideoEditor
        activity={activity({ media_asset: 5 })}
        disabled={false}
        save={vi.fn(async () => {})}
        refresh={refresh}
      />,
    )
    expect(await screen.findByText(/Processing/)).toBeInTheDocument()
    expect(refresh).not.toHaveBeenCalled()
    current = READY
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100)
    })
    await screen.findByText(/Ready · 2:05/)
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('does not refresh when the video was already ready', async () => {
    useRoutes({ 'GET /api/v1/authoring/media/5/': () => ({ status: 200, body: READY }) })
    const refresh = vi.fn(async () => {})
    render(
      <VideoEditor
        activity={activity({ media_asset: 5 })}
        disabled={false}
        save={vi.fn(async () => {})}
        refresh={refresh}
      />,
    )
    await screen.findByText(/Ready · 2:05/)
    expect(refresh).not.toHaveBeenCalled()
  })

  it('refuses the wrong kind of file before sending anything', async () => {
    useRoutes({})
    const { save } = mount()
    await screen.findByText(/up to 1024 MB/)
    choose('notes.txt')
    expect(screen.getByRole('alert')).toHaveTextContent('We can’t use that kind of file. Upload one of: MP4, MOV, WEBM.')
    expect(save).not.toHaveBeenCalled()
  })

  it('refuses a file over the size limit before sending anything', async () => {
    useRoutes({})
    mount()
    await screen.findByText(/up to 1024 MB/)
    choose('big.mp4', 2000 * 1024 * 1024)
    expect(screen.getByRole('alert')).toHaveTextContent('larger than the 1024 MB limit')
  })

  it('shows the server’s plain sentence when it refuses the upload', async () => {
    useRoutes({})
    const { save } = mount()
    await screen.findByText(/up to 1024 MB/)
    choose()
    await act(async () =>
      FakeXhr.last.finish(400, { detail: 'This video is longer than the 2-hour limit.' }),
    )
    expect(screen.getByRole('alert')).toHaveTextContent('This video is longer than the 2-hour limit.')
    expect(save).not.toHaveBeenCalled()
  })

  it('says so, in words, when the connection drops', async () => {
    useRoutes({})
    mount()
    await screen.findByText(/up to 1024 MB/)
    choose()
    await act(async () => {
      FakeXhr.last.onerror?.()
    })
    expect(screen.getByRole('alert')).toHaveTextContent('The upload was interrupted')
  })

  it('shows a failed video with the reason and a way to try again', async () => {
    let current: MediaAsset = asset({
      status: 'failed',
      error: 'The server ran out of storage space. Try again once space is freed up.',
      retryable: true,
    })
    useRoutes({
      'GET /api/v1/authoring/media/5/': () => ({ status: 200, body: current }),
      'POST /api/v1/authoring/media/5/retry/': () => {
        current = asset()
        return { status: 200, body: current }
      },
    })
    mount({ media_asset: 5 })
    expect(await screen.findByRole('alert')).toHaveTextContent('ran out of storage space')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText(/Processing/)).toBeInTheDocument()
    expect(calls).toContainEqual({ method: 'POST', path: '/api/v1/authoring/media/5/retry/' })
  })

  it('does not offer a retry that cannot work', async () => {
    useRoutes({
      'GET /api/v1/authoring/media/5/': () => ({
        status: 200,
        body: asset({ status: 'failed', error: 'That file doesn’t look like a video we can read.' }),
      }),
    })
    mount({ media_asset: 5 })
    expect(await screen.findByRole('alert')).toHaveTextContent('doesn’t look like a video')
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('does not break when the attached video belongs to someone else', async () => {
    useRoutes({})
    mount({ media_asset: 5 })
    expect(await screen.findByText(/can’t see its status here/)).toBeInTheDocument()
  })

  it('offers no way to change a locked course’s video', async () => {
    useRoutes({ 'GET /api/v1/authoring/media/5/': () => ({ status: 200, body: READY }) })
    mount({ media_asset: 5 }, { disabled: true })
    await screen.findByText(/Ready · 2:05/)
    expect(screen.queryByLabelText('Choose a video file')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Replace/ })).not.toBeInTheDocument()
  })
})

describe('Video editor — YouTube', () => {
  it('switches source and saves it', async () => {
    useRoutes({})
    const { save } = mount()
    fireEvent.click(screen.getByRole('radio', { name: 'YouTube link' }))
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastSaved(save)).toMatchObject({ source: 'youtube' })
  })

  it('accepts a real link and previews it in an embedded player — not a link out', async () => {
    useRoutes({})
    const { save } = mount({ source: 'youtube', youtube_url: 'https://youtu.be/dQw4w9WgXcQ' })
    const frame = screen.getByTitle('Preview of the YouTube video')
    expect(frame).toHaveAttribute('src', 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ')
    expect(screen.queryByRole('link')).not.toBeInTheDocument()

    const field = screen.getByLabelText('YouTube link')
    fireEvent.change(field, { target: { value: 'https://www.youtube.com/watch?v=abcdefghijk' } })
    fireEvent.blur(field)
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastSaved(save)).toMatchObject({
      source: 'youtube',
      youtube_url: 'https://www.youtube.com/watch?v=abcdefghijk',
    })
  })

  it.each([
    'https://example.com/watch?v=dQw4w9WgXcQ',
    'https://youtube.com.evil.io/watch?v=dQw4w9WgXcQ',
    'https://www.youtube.com/watch?v=short',
    'javascript:alert(1)',
    'not a link',
  ])('refuses %s with a sentence and saves nothing', async (bad) => {
    useRoutes({})
    const { save } = mount({ source: 'youtube', youtube_url: '' })
    const field = screen.getByLabelText('YouTube link')
    fireEvent.change(field, { target: { value: bad } })
    fireEvent.blur(field)
    expect(await screen.findByText(/Paste a valid YouTube link/)).toBeInTheDocument()
    expect(save).not.toHaveBeenCalled()
  })
})

describe('Video editor — how watching is counted', () => {
  it('shows the defaults and explains them in plain words', async () => {
    useRoutes({})
    mount()
    expect(screen.getByLabelText('Share that must be watched (%)')).toHaveValue(90)
    expect(screen.getByLabelText('Fastest speed that counts')).toHaveValue(1)
    expect(screen.getByText(/Skipping ahead doesn’t count/)).toBeInTheDocument()
  })

  it('saves a new share and keeps the rest of the settings', async () => {
    useRoutes({})
    const { save } = mount({ media_asset: 5 })
    const field = screen.getByLabelText('Share that must be watched (%)')
    fireEvent.change(field, { target: { value: '80' } })
    fireEvent.blur(field)
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastSaved(save)).toMatchObject({ media_asset: 5, completion_threshold: 0.8 })
  })

  it.each([
    ['Share that must be watched (%)', '30', /from 50 to 100/],
    ['Share that must be watched (%)', '101', /from 50 to 100/],
    ['Fastest speed that counts', '5', /from 0.25 to 2/],
    ['Fastest speed that counts', '', /from 0.25 to 2/],
  ])('refuses %s = "%s"', async (label, value, message) => {
    useRoutes({})
    const { save } = mount()
    const field = screen.getByLabelText(label)
    fireEvent.change(field, { target: { value } })
    fireEvent.blur(field)
    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(save).not.toHaveBeenCalled()
  })
})


describe('Video editor — Google Drive', () => {
  const FILE = '1AbCdEfGhIjKlMnOpQrStUvWx'

  it('is offered as a source and saves the choice', async () => {
    useRoutes({})
    const { save } = mount()
    fireEvent.click(screen.getByRole('radio', { name: 'Google Drive link' }))
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastSaved(save)).toMatchObject({ source: 'drive' })
  })

  it('previews the file in an embedded player, and says what it can’t measure', async () => {
    useRoutes({})
    mount({
      source: 'drive',
      drive_url: `https://drive.google.com/file/d/${FILE}/view?usp=sharing`,
    })
    expect(screen.getByTitle('Preview of the Google Drive video')).toHaveAttribute(
      'src',
      `https://drive.google.com/file/d/${FILE}/preview`,
    )
    expect(screen.getByText(/Anyone with the link/)).toBeInTheDocument()
    expect(screen.getByText(/learners confirm it/)).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    // Nothing is measured, so the watching settings don't apply.
    expect(screen.queryByText('How watching is counted')).not.toBeInTheDocument()
  })

  it('saves a share link in any of the usual forms', async () => {
    useRoutes({})
    const { save } = mount({ source: 'drive', drive_url: '' })
    const field = screen.getByLabelText('Google Drive link', { selector: 'input' })
    fireEvent.change(field, { target: { value: `https://drive.google.com/open?id=${FILE}` } })
    fireEvent.blur(field)
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastSaved(save)).toMatchObject({
      source: 'drive',
      drive_url: `https://drive.google.com/open?id=${FILE}`,
    })
  })

  it.each([
    `https://example.com/file/d/${FILE}/view`,
    `https://drive.google.com.evil.io/file/d/${FILE}/view`,
    `https://docs.google.com/file/d/${FILE}/view`,
    'https://drive.google.com/drive/folders/' + FILE,
    'javascript:alert(1)',
    'not a link',
  ])('refuses %s with a sentence and saves nothing', async (bad) => {
    useRoutes({})
    const { save } = mount({ source: 'drive', drive_url: '' })
    const field = screen.getByLabelText('Google Drive link', { selector: 'input' })
    fireEvent.change(field, { target: { value: bad } })
    fireEvent.blur(field)
    expect(await screen.findByText(/Paste a valid Google Drive link/)).toBeInTheDocument()
    expect(save).not.toHaveBeenCalled()
  })
})
