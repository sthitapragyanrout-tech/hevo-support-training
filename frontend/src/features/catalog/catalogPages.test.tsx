import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from '../../App'
import { AuthProvider } from '../../lib/auth'
import { mockLearnerApi } from './testApi'

function mockApi(options: Parameters<typeof mockLearnerApi>[0] = {}) {
  return mockLearnerApi(options)
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.title = ''
})

describe('My courses', () => {
  it('lists courses as rows with honest not-started meta', async () => {
    mockApi()
    renderAt('/')
    const link = await screen.findByRole('link', { name: /CX Onboarding/ })
    expect(link).toHaveAttribute('href', '/courses/1')
    expect(link).toHaveTextContent('Not started')
    expect(link).toHaveTextContent('2 lessons')
    expect(link).toHaveTextContent('2 modules')
    expect(link).toHaveTextContent('~45 min')
    expect(link).toHaveTextContent('Start course')
    expect(link).toHaveTextContent('Learn the platform.')
  })
})

describe('Course landing', () => {
  it('shows outcomes, a derived "Includes" fact and the module journey', async () => {
    mockApi()
    renderAt('/courses/1')
    const outcomes = await screen.findByRole('heading', { name: 'What you’ll learn' })
    const section = outcomes.closest('section')!
    expect(within(section).getByText('Place a problem')).toBeInTheDocument()
    expect(within(section).getByText('Read a log')).toBeInTheDocument()

    const glance = screen.getByRole('region', { name: 'At a glance' })
    expect(glance).toHaveTextContent('readings, videos, quizzes') // from the sections' activities
    expect(glance).toHaveTextContent('2 in 2 modules')
  })

  it('shows the hero, a Start course CTA and no progress bar', async () => {
    mockApi()
    renderAt('/courses/1')

    expect(await screen.findByRole('heading', { level: 1, name: 'CX Onboarding' })).toBeInTheDocument()
    expect(screen.getByText('Not started · 2 lessons · 2 modules · ~45 min')).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument()
    expect(screen.getByText(/Starts with/)).toHaveTextContent('Starts with Pipelines · 33 min')
    expect(screen.getByRole('link', { name: /start course/i })).toHaveAttribute(
      'href',
      '/courses/1/lessons/3',
    )
  })

  it('lists modules and lessons; sections are not separate lessons', async () => {
    mockApi()
    renderAt('/courses/1')
    await screen.findByRole('heading', { name: 'Your path through the course' })

    expect(screen.getByRole('heading', { level: 3, name: /Fundamentals/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Pipelines/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Failures/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Sources/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Logs/ })).not.toBeInTheDocument()
  })

  it('filters lessons from the quiet filter field (including section text)', async () => {
    mockApi()
    renderAt('/courses/1')
    const filter = await screen.findByRole('searchbox', { name: 'Filter lessons' })

    fireEvent.change(filter, { target: { value: 'logs' } })
    expect(screen.getByRole('link', { name: /Failures/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Pipelines/ })).not.toBeInTheDocument()

    fireEvent.change(filter, { target: { value: 'zzz' } })
    expect(screen.getByText(/No lessons match/)).toBeInTheDocument()
  })

  it('shows a not-found state for an unknown course', async () => {
    mockApi({ courseStatus: 404 })
    renderAt('/courses/1')
    expect(await screen.findByRole('heading', { name: 'Course not found' })).toBeInTheDocument()
  })
})

describe('Lesson page', () => {
  it('renders the lesson with its intro, then each section with its own activities', async () => {
    mockApi()
    renderAt('/courses/1/lessons/3')

    expect(await screen.findByRole('heading', { level: 1, name: 'Pipelines' })).toBeInTheDocument()
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(crumbs).toHaveTextContent('CX Onboarding')
    expect(crumbs).toHaveTextContent('01 Fundamentals')
    expect(screen.getByText('Lesson 1 of 1')).toBeInTheDocument()
    expect(screen.getByText('How data flows from A to B.')).toBeInTheDocument()

    // Sections are second-level headings; headings inside a section nest below them.
    expect(screen.getByRole('heading', { level: 2, name: 'Sources' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Ingestion' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: 'What is a source?' })).toBeInTheDocument()

    // The activities belong to the Sources section.
    const sources = screen.getByRole('heading', { level: 2, name: 'Sources' }).closest('section')!
    expect(within(sources).getByText('Read the docs')).toBeInTheDocument()
    expect(within(sources).getByText('Sources quiz')).toBeInTheDocument()
    const ingestion = screen.getByRole('heading', { level: 2, name: 'Ingestion' }).closest('section')!
    expect(within(ingestion).queryByText('Read the docs')).not.toBeInTheDocument()
  })

  it('does not render raw HTML embedded in lesson Markdown', async () => {
    mockApi()
    const { container } = renderAt('/courses/1/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })
    const article = container.querySelector('article')!
    expect(article.querySelector('script')).toBeNull()
    expect(article.querySelector('b')).toBeNull()
  })

  it('lists the sections in the "In this lesson" outline', async () => {
    mockApi()
    renderAt('/courses/1/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })
    const outline = screen.getByRole('navigation', { name: 'In this lesson' })
    const links = within(outline).getAllByRole('link')
    expect(links.map((l) => l.textContent)).toEqual(['Sources', 'Ingestion'])
    expect(links[0]).toHaveAttribute('href', expect.stringMatching(/^#section-4$/))
  })

  it('shows Up next with the next lesson’s summary and minutes', async () => {
    mockApi()
    renderAt('/courses/1/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })

    const upNext = screen.getByRole('link', { name: /Up next.*Failures/ })
    expect(upNext).toHaveAttribute('href', '/courses/1/lessons/7')
    expect(upNext).toHaveTextContent('Module 02') // crossing into a new module is called out
    expect(upNext).toHaveTextContent('Read the evidence before you guess.')
    expect(upNext).toHaveTextContent('12 min')
    expect(screen.queryByText(/Previous lesson/)).not.toBeInTheDocument()
  })

  it('ends the course with a return-to-overview link instead of Up next', async () => {
    mockApi()
    renderAt('/courses/1/lessons/7')
    await screen.findByRole('heading', { level: 1, name: 'Failures' })
    expect(screen.getByRole('link', { name: /Previous lesson: Pipelines/ })).toHaveAttribute(
      'href',
      '/courses/1/lessons/3',
    )
    expect(screen.getByText('You’ve reached the end')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Return to the course overview/ })).toHaveAttribute(
      'href',
      '/courses/1',
    )
    expect(screen.queryByText(/Up next/)).not.toBeInTheDocument()
  })

  it('redirects a module id to its first lesson', async () => {
    mockApi()
    renderAt('/courses/1/lessons/2')
    expect(await screen.findByRole('heading', { level: 1, name: 'Pipelines' })).toBeInTheDocument()
  })

  it('redirects a section id to the lesson that contains it', async () => {
    mockApi()
    renderAt('/courses/1/lessons/8')
    expect(await screen.findByRole('heading', { level: 1, name: 'Failures' })).toBeInTheDocument()
  })

  it('shows a not-found state for an unknown lesson', async () => {
    mockApi()
    renderAt('/courses/1/lessons/999')
    expect(await screen.findByRole('heading', { name: 'Lesson not found' })).toBeInTheDocument()
  })
})

describe('Course sidebar', () => {
  async function sidebar() {
    mockApi()
    renderAt('/courses/1/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })
    return screen.getByRole('navigation', { name: 'Course contents' })
  }

  it('lists lessons (not sections) and marks the current lesson', async () => {
    const nav = await sidebar()
    const current = within(nav).getByRole('link', { name: /Pipelines/ })
    expect(current).toHaveAttribute('aria-current', 'page')
    expect(current).toHaveTextContent('Current lesson')
    expect(within(nav).queryByRole('link', { name: /Sources/ })).not.toBeInTheDocument()
  })

  it('opens only the active module and lets the learner expand another', async () => {
    const nav = await sidebar()
    expect(within(nav).queryByRole('link', { name: /Failures/ })).not.toBeInTheDocument()

    fireEvent.click(within(nav).getByRole('button', { name: /Troubleshooting/ }))
    expect(within(nav).getByRole('link', { name: /Failures/ })).toBeInTheDocument()
  })

  it('keeps the lesson filter hidden until asked for, then filters', async () => {
    const nav = await sidebar()
    expect(within(nav).queryByRole('searchbox')).not.toBeInTheDocument()

    fireEvent.click(within(nav).getByRole('button', { name: 'Filter lessons' }))
    fireEvent.change(within(nav).getByRole('searchbox'), { target: { value: 'logs' } })

    expect(within(nav).getByRole('link', { name: /Failures/ })).toBeInTheDocument()
    expect(within(nav).queryByRole('link', { name: /Pipelines/ })).not.toBeInTheDocument()
  })
})

describe('Mobile drawer', () => {
  it('replaces the sidebar with a Contents drawer that closes on Escape', async () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ matches: true, addEventListener: () => {}, removeEventListener: () => {} })),
    )
    mockApi()
    renderAt('/courses/1/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    const opener = screen.getByRole('button', { name: /contents/i })
    fireEvent.click(opener)

    const dialog = screen.getByRole('dialog', { name: 'Course contents' })
    expect(within(dialog).getByRole('link', { name: /Pipelines/ })).toBeInTheDocument()

    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })
})
