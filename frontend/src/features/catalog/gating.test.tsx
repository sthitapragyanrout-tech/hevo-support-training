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

const posted = (calls: { method: string; path: string }[], fragment: string) =>
  calls.filter((c) => c.method === 'POST' && c.path.includes(fragment))

const sidebar = () => screen.getByRole('navigation', { name: 'Course contents' })

/** Open the Troubleshooting module in the sidebar, where Failures lives. */
function openTroubleshooting() {
  fireEvent.click(within(sidebar()).getByRole('button', { name: /Troubleshooting/ }))
}

describe('A course that goes in order — the sidebar', () => {
  it('shows the lesson that is not open yet as locked, not as a link', async () => {
    mockLearnerApi({ learningOrder: 'sequential' })
    renderAt('/courses/1/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })
    await waitFor(() => expect(within(sidebar()).getByRole('link', { name: /Pipelines/ })).toBeInTheDocument())
    openTroubleshooting()

    const row = await within(sidebar()).findByText('Failures')
    const locked = row.closest('[aria-disabled="true"]') as HTMLElement
    expect(locked).not.toBeNull()
    expect(locked).toHaveTextContent('Locked') // icon + words, never colour alone
    expect(locked).toHaveAttribute('title', 'Unlocks when you complete “Pipelines”')
    expect(within(sidebar()).queryByRole('link', { name: /Failures/ })).not.toBeInTheDocument()
  })

  it('shows no locks at all when learners can open any lesson', async () => {
    mockLearnerApi({ learningOrder: 'free' })
    renderAt('/courses/1/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })
    openTroubleshooting()
    expect(await within(sidebar()).findByRole('link', { name: /Failures/ })).toBeInTheDocument()
    expect(within(sidebar()).queryByText('Locked')).not.toBeInTheDocument()
  })

  it('opens the next lesson the moment this one is completed', async () => {
    mockLearnerApi({ learningOrder: 'sequential', activities: { 1: 'completed' } })
    renderAt('/courses/1/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })
    openTroubleshooting()
    await within(sidebar()).findByText('Failures')
    expect(within(sidebar()).queryByRole('link', { name: /Failures/ })).not.toBeInTheDocument()

    const button = await screen.findByRole('button', { name: 'Mark complete' })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(button)

    expect(await within(sidebar()).findByRole('link', { name: /Failures/ })).toBeInTheDocument()
    expect(within(sidebar()).queryByText('Locked')).not.toBeInTheDocument()
  })

  it('locks it again if the earlier lesson is marked incomplete', async () => {
    mockLearnerApi({
      learningOrder: 'sequential',
      activities: { 1: 'completed' },
      completedLessons: [3],
    })
    renderAt('/courses/1/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })
    openTroubleshooting()
    expect(await within(sidebar()).findByRole('link', { name: /Failures/ })).toBeInTheDocument()

    fireEvent.click(await screen.findByRole('button', { name: 'Mark incomplete' }))
    await waitFor(() =>
      expect(within(sidebar()).queryByRole('link', { name: /Failures/ })).not.toBeInTheDocument(),
    )
    expect(within(sidebar()).getByText('Failures').closest('[aria-disabled="true"]')).not.toBeNull()
  })
})

describe('A locked lesson', () => {
  it('says why, offers the one thing to do, and shows no content', async () => {
    const { calls } = mockLearnerApi({ learningOrder: 'sequential' })
    renderAt('/courses/1/lessons/7')

    expect(await screen.findByRole('heading', { level: 1, name: 'Failures' })).toBeInTheDocument()
    expect(await screen.findByText('This lesson isn’t open yet')).toBeInTheDocument()
    expect(screen.getByText(/It unlocks when you complete/)).toHaveTextContent('Pipelines')
    expect(screen.getByRole('link', { name: /Go to Pipelines/ })).toHaveAttribute(
      'href',
      '/courses/1/lessons/3',
    )
    // None of the lesson is on the page, and nothing can be recorded.
    expect(screen.queryByText('Read the evidence before you guess.')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mark complete' })).not.toBeInTheDocument()
    expect(posted(calls, '/progress/')).toHaveLength(0)
  })

  it('is just a lesson once it is open', async () => {
    mockLearnerApi({ learningOrder: 'sequential', completedLessons: [3] })
    renderAt('/courses/1/lessons/7')
    await screen.findByRole('heading', { level: 1, name: 'Failures' })
    expect(await screen.findByRole('button', { name: 'Mark complete' })).toBeInTheDocument()
    expect(screen.queryByText('This lesson isn’t open yet')).not.toBeInTheDocument()
  })

  it('shows what is coming and why it is not open, in the footer of the lesson before it', async () => {
    mockLearnerApi({ learningOrder: 'sequential' })
    renderAt('/courses/1/lessons/3')
    const upNext = await screen.findByRole('link', { name: /Up next/ })
    await waitFor(() => expect(upNext).toHaveTextContent('Locked'))
    expect(upNext).toHaveTextContent('Failures')
    expect(upNext).toHaveTextContent('Unlocks when you complete “Pipelines”.')
  })

  it('footer no longer says locked once the lesson is done', async () => {
    mockLearnerApi({ learningOrder: 'sequential', completedLessons: [3] })
    renderAt('/courses/1/lessons/3')
    const upNext = await screen.findByRole('link', { name: /Up next/ })
    await waitFor(() => expect(upNext).not.toHaveTextContent('Locked'))
    expect(upNext).toHaveTextContent('Read the evidence before you guess.')
  })
})

describe('The landing page and My courses', () => {
  it('lists the locked lesson with the reason, and marks what is up next', async () => {
    mockLearnerApi({ learningOrder: 'sequential' })
    renderAt('/courses/1')
    const failures = (await screen.findByRole('link', { name: /Failures/ })).closest('a')!
    await waitFor(() => expect(failures).toHaveTextContent('Unlocks when you complete “Pipelines”'))
    expect(failures).toHaveTextContent('Locked')
    const rows = screen.getAllByRole('link', { name: /Pipelines/ })
    expect(rows.some((r) => r.textContent?.includes('Up next'))).toBe(true)
  })

  it('sends "Continue learning" to the lesson the server says is next', async () => {
    mockLearnerApi({
      learningOrder: 'sequential',
      completedLessons: [3],
      activities: { 1: 'completed' },
    })
    renderAt('/courses/1')
    const cta = await screen.findByRole('link', { name: /continue learning/i })
    expect(cta).toHaveAttribute('href', '/courses/1/lessons/7')
  })

  it('says what is next on My courses for a course in progress', async () => {
    mockLearnerApi({ learningOrder: 'sequential', activities: { 1: 'completed' } })
    renderAt('/')
    const row = await screen.findByRole('link', { name: /CX Onboarding/ })
    expect(row).toHaveTextContent('In progress')
    expect(row).toHaveTextContent('Next: Pipelines')
  })

  it('does not say it for a course nobody has started', async () => {
    mockLearnerApi()
    renderAt('/')
    const row = await screen.findByRole('link', { name: /CX Onboarding/ })
    expect(row).not.toHaveTextContent('Next:')
  })
})

describe('The author’s preview of a course that goes in order', () => {
  it('stays open, and says so', async () => {
    mockLearnerApi({ learningOrder: 'sequential', user: { capabilities: ['catalog.author_content'] } })
    const base = globalThis.fetch as unknown as (u: string, i?: RequestInit) => Promise<Response>
    vi.stubGlobal(
      'fetch',
      vi.fn((u: string, i?: RequestInit) =>
        base(u.replace('/api/v1/authoring/courses/1/preview/', '/api/v1/catalog/courses/1/'), i),
      ),
    )
    renderAt('/studio/courses/1/preview/lessons/7')
    expect(await screen.findByRole('note')).toHaveTextContent('set to go in order')
    expect(await screen.findByRole('heading', { level: 1, name: 'Failures' })).toBeInTheDocument()
    expect(screen.queryByText('This lesson isn’t open yet')).not.toBeInTheDocument()
  })
})
