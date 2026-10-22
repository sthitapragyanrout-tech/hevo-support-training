import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from '../../App'
import { AuthProvider } from '../../lib/auth'
import { mockLearnerApi } from './testApi'

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

/** Progress loads just after the page does; wait until it can be recorded. */
const recordable = (name: string | RegExp) =>
  waitFor(() => expect(screen.getByRole('button', { name })).toBeEnabled())

const posted = (calls: { method: string; path: string }[], suffix: string, method = 'POST') =>
  calls.filter((c) => c.method === method && c.path.endsWith(suffix))

describe('Reading activity', () => {
  it('opens the reading in a new tab, records the start, then records "read"', async () => {
    const { calls } = mockLearnerApi()
    renderAt('/courses/1/lessons/3')

    const open = await screen.findByRole('link', { name: /Open reading/ })
    expect(open).toHaveAttribute('href', 'https://docs.example.com/sources')
    expect(open).toHaveAttribute('target', '_blank')
    expect(open).toHaveAttribute('rel', expect.stringContaining('noopener'))
    expect(screen.getByText(/Reading · about 8 min · Required/)).toBeInTheDocument()

    await recordable('I’ve read this')
    fireEvent.click(open)
    await waitFor(() => expect(posted(calls, '/activities/1/start/')).toHaveLength(1))

    fireEvent.click(screen.getByRole('button', { name: 'I’ve read this' }))
    expect(await screen.findByText('Read')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Open reading/ })).not.toBeInTheDocument()
    expect(posted(calls, '/activities/1/complete/')).toHaveLength(1)
  })

  it('does not yank the learner back to the top of the lesson when they mark it', async () => {
    mockLearnerApi()
    renderAt('/courses/1/lessons/3')
    await screen.findByRole('link', { name: /Open reading/ })
    await recordable('I’ve read this')

    document.documentElement.scrollTop = 640 // they are partway down the page
    fireEvent.click(screen.getByRole('button', { name: 'I’ve read this' }))
    await screen.findByText('Read')
    expect(document.documentElement.scrollTop).toBe(640)
  })

  it('can be marked as unread again', async () => {
    const { calls } = mockLearnerApi({ activities: { 1: 'completed' } })
    renderAt('/courses/1/lessons/3')
    await recordable('Mark as unread')
    fireEvent.click(screen.getByRole('button', { name: 'Mark as unread' }))
    expect(await screen.findByRole('button', { name: 'I’ve read this' })).toBeInTheDocument()
    expect(posted(calls, '/activities/1/complete/', 'DELETE')).toHaveLength(1)
  })

  it('shows activity types that are not built yet in the same frame, as "Available soon"', async () => {
    mockLearnerApi()
    renderAt('/courses/1/lessons/3')
    const video = await screen.findByText('Ingestion walkthrough')
    expect(video.closest('li')).toHaveTextContent('Available soon')
    expect(screen.getByText(/Video · Required/)).toBeInTheDocument()
  })
})

describe('Lesson completion', () => {
  it('is blocked, with a plain-language reason, until the required reading is done', async () => {
    mockLearnerApi()
    renderAt('/courses/1/lessons/3')
    const button = await screen.findByRole('button', { name: 'Mark complete' })
    await waitFor(() => expect(screen.getByText(/Finish the 1 required activity above first/)).toBeInTheDocument())
    expect(button).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'I’ve read this' }))
    await waitFor(() => expect(button).toBeEnabled())
    expect(screen.queryByText(/Finish the 1 required/)).not.toBeInTheDocument()
  })

  it('does not wait on required activities that cannot be completed yet (the video)', async () => {
    mockLearnerApi({ activities: { 1: 'completed' } })
    renderAt('/courses/1/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })
    await recordable('Mark complete')
  })

  it('records completion, shows it, and can be undone', async () => {
    const { calls } = mockLearnerApi({ activities: { 1: 'completed' } })
    renderAt('/courses/1/lessons/3')

    await recordable('Mark complete')
    fireEvent.click(screen.getByRole('button', { name: 'Mark complete' }))
    expect(await screen.findByText('Lesson complete')).toBeInTheDocument()
    expect(posted(calls, '/lessons/3/complete/')).toHaveLength(1)
    // …and the sidebar reflects it as a status, not just a colour.
    const nav = screen.getByRole('navigation', { name: 'Course contents' })
    expect(within(nav).getByRole('link', { name: /Pipelines/ })).toHaveTextContent('Completed')

    fireEvent.click(screen.getByRole('button', { name: 'Mark incomplete' }))
    expect(await screen.findByRole('button', { name: 'Mark complete' })).toBeInTheDocument()
    expect(posted(calls, '/lessons/3/complete/', 'DELETE')).toHaveLength(1)
  })

  it('a lesson with nothing to finish can simply be marked complete', async () => {
    mockLearnerApi()
    renderAt('/courses/1/lessons/7')
    await screen.findByRole('heading', { level: 1, name: 'Failures' })
    await recordable('Mark complete')
  })

  it('rolls back and explains when the server says no', async () => {
    mockLearnerApi({
      activities: { 1: 'completed' },
      fail: {
        'POST /api/v1/progress/lessons/3/complete/': {
          status: 409,
          detail: 'Finish the 1 required activity in this lesson first.',
        },
      },
    })
    renderAt('/courses/1/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })
    await recordable('Mark complete')
    fireEvent.click(screen.getByRole('button', { name: 'Mark complete' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Finish the 1 required activity')
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeInTheDocument()
    expect(screen.queryByText('Lesson complete')).not.toBeInTheDocument()
  })

  it('never shows ids, codes or JSON to the learner', async () => {
    mockLearnerApi({ activities: { 1: 'completed' }, completedLessons: [3] })
    renderAt('/courses/1/lessons/3')
    await screen.findByText('Lesson complete')
    expect(document.body.textContent).not.toMatch(/\b409\b|\bundefined\b|\[object|"completed"/)
  })
})

describe('Progress across the app', () => {
  it('landing: Continue learning goes to the first unfinished lesson, with real counts', async () => {
    mockLearnerApi({ completedLessons: [3] })
    renderAt('/courses/1')
    const cta = await screen.findByRole('link', { name: /continue learning/i })
    expect(cta).toHaveAttribute('href', '/courses/1/lessons/7')
    expect(screen.getByRole('progressbar', { name: 'Course progress' })).toHaveAttribute(
      'aria-valuenow',
      '1',
    )
    expect(screen.getByText('1 of 2 lessons completed')).toBeInTheDocument()
    expect(screen.getByText(/Up next:/)).toHaveTextContent('Failures')
  })

  it('landing: a finished course says so and offers Review', async () => {
    mockLearnerApi({ completedLessons: [3, 7] })
    renderAt('/courses/1')
    expect(await screen.findByRole('link', { name: /review course/i })).toBeInTheDocument()
    expect(screen.getAllByText('Completed').length).toBeGreaterThan(0)
    expect(screen.getByText(/completed every lesson/)).toBeInTheDocument()
  })

  it('landing: honest "Not started" with no bar until the learner has done something', async () => {
    mockLearnerApi()
    renderAt('/courses/1')
    expect(await screen.findByRole('link', { name: /start course/i })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Not started · 2 lessons · 2 modules · ~45 min')).toBeInTheDocument())
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('landing: just opening an activity counts as having started', async () => {
    mockLearnerApi({ activities: { 1: 'started' } })
    renderAt('/courses/1')
    expect(await screen.findByRole('link', { name: /continue learning/i })).toHaveAttribute(
      'href',
      '/courses/1/lessons/3',
    )
  })

  it('My courses: Not started → In progress → Completed, each with the right action', async () => {
    mockLearnerApi()
    const { unmount } = renderAt('/')
    let row = await screen.findByRole('link', { name: /CX Onboarding/ })
    expect(row).toHaveTextContent('Not started')
    expect(row).toHaveTextContent('Start course')
    unmount()

    mockLearnerApi({ completedLessons: [7] })
    const second = renderAt('/')
    row = await screen.findByRole('link', { name: /CX Onboarding/ })
    expect(row).toHaveTextContent('In progress · 1 of 2')
    expect(row).toHaveTextContent('Continue')
    second.unmount()

    mockLearnerApi({ completedLessons: [3, 7] })
    renderAt('/')
    row = await screen.findByRole('link', { name: /CX Onboarding/ })
    expect(row).toHaveTextContent('Completed')
    expect(row).toHaveTextContent('Review')
  })

  it('sidebar: completed lessons are marked with text, and unfinished ones are not', async () => {
    mockLearnerApi({ completedLessons: [7] })
    renderAt('/courses/1/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })
    fireEvent.click(screen.getByRole('button', { name: /Troubleshooting/ }))
    const nav = screen.getByRole('navigation', { name: 'Course contents' })
    expect(within(nav).getByRole('link', { name: /Failures/ })).toHaveTextContent('Completed')
  })
})

describe('Author preview', () => {
  it('records nothing: no progress calls, no recordable buttons, and says why', async () => {
    const { calls } = mockLearnerApi({ user: { capabilities: ['catalog.author_content'] } })
    // Route the preview endpoint to the same tree.
    const base = globalThis.fetch as unknown as (u: string, i?: RequestInit) => Promise<Response>
    vi.stubGlobal('fetch', vi.fn((u: string, i?: RequestInit) =>
      base(u.replace('/api/v1/authoring/courses/1/preview/', '/api/v1/catalog/courses/1/'), i),
    ))
    renderAt('/studio/courses/1/preview/lessons/3')

    expect(await screen.findByText(/Previewing the draft/)).toBeInTheDocument()
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })
    expect(screen.getByRole('button', { name: 'I’ve read this' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeDisabled()
    expect(screen.getByText('Progress isn’t recorded in preview.')).toBeInTheDocument()
    // The link is still usable so an author can check it.
    expect(screen.getByRole('link', { name: /Open reading/ })).toBeInTheDocument()
    expect(calls.some((c) => c.path.includes('/progress/'))).toBe(false)
  })
})
