import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, page, renderAt, type Handler } from './testHelpers'

const VIEW = 'progress.view_results'
const MANAGE = 'progress.manage_attempts'
const AUDIT = 'audit.view_audit'

afterEach(() => vi.unstubAllGlobals())


const LEARNERS = [
  {
    id: 11,
    name: 'Ann Ames',
    email: 'ann@example.com',
    employee_id: null,
    lessons_completed: 2,
    quiz_attempts: 3,
    last_activity: '2026-10-20T10:00:00Z',
  },
  {
    id: 12,
    name: 'bob@example.com',
    email: 'bob@example.com',
    employee_id: 'E12',
    lessons_completed: 0,
    quiz_attempts: 2,
    last_activity: null,
  },
]

const COURSES = { results: [{ id: 1, title: 'CX Onboarding' }, { id: 2, title: 'Escalations' }] }

const DETAIL = {
  id: 11,
  name: 'Ann Ames',
  email: 'ann@example.com',
  employee_id: null,
  courses: [
    {
      course_id: 1,
      title: 'CX Onboarding',
      version: 1,
      state: 'published',
      lessons_total: 3,
      lessons_completed: 2,
      activities: [
        {
          id: 5,
          title: 'Read the docs',
          type: 'reading',
          lesson: 'Pipelines',
          required: true,
          state: 'completed',
          scored: false,
          best_score: null,
          attempts: [],
          max_attempts: 3,
        },
        {
          id: 6,
          title: 'Sources quiz',
          type: 'mcq',
          lesson: 'Pipelines',
          required: true,
          state: 'exhausted',
          scored: true,
          best_score: 0.5,
          max_attempts: 2,
          attempts: [
            { number: 1, score: 0, correct: 0, total: 2, passed: false, submitted_at: '2026-10-20T10:00:00Z' },
            { number: 2, score: 0.5, correct: 1, total: 2, passed: false, submitted_at: '2026-10-21T10:00:00Z' },
          ],
        },
      ],
    },
  ],
}

describe('Console entry', () => {
  it('shows the Admin link only to people who may use it', async () => {
    mockApi([VIEW], {
      'GET /api/v1/admin/results/learners/': page(LEARNERS),
      'GET /api/v1/admin/results/courses/': COURSES,
      'GET /api/v1/catalog/courses/': [],
    })
    renderAt('/')
    expect(await screen.findByRole('link', { name: 'Admin' })).toHaveAttribute('href', '/admin')
  })

  it('hides it from a learner, who is told they have no access if they type the URL', async () => {
    mockApi([], { 'GET /api/v1/catalog/courses/': [] })
    renderAt('/')
    await screen.findByText('My courses', { selector: 'h1' }).catch(() => null)
    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument()

    mockApi([], {})
    renderAt('/admin/results/learners')
    expect(await screen.findByText('You don’t have access to this area')).toBeInTheDocument()
  })

  it('opens the first screen the person may use, and lists only those in the rail', async () => {
    mockApi([AUDIT], { 'GET /api/v1/admin/audit/': page([]), 'GET /api/v1/admin/audit/actions/': { results: [] } })
    renderAt('/admin')
    const rail = await screen.findByRole('navigation', { name: 'Admin sections' })
    expect(within(rail).getByRole('link', { name: 'Audit log' })).toBeInTheDocument()
    expect(within(rail).queryByRole('link', { name: 'Learners' })).not.toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Audit log' })).toBeInTheDocument()
  })

  it('does not let someone with only results access open the audit log', async () => {
    mockApi([VIEW], {})
    renderAt('/admin/audit')
    expect(await screen.findByText('You don’t have access to this area')).toBeInTheDocument()
  })

  it('offers the emergency back-office only to superusers', async () => {
    mockApi([], { 'GET /api/v1/catalog/courses/': [] }, { is_superuser: true })
    renderAt('/')
    fireEvent.click(await screen.findByRole('button', { name: 'Account menu' }))
    expect(await screen.findByRole('link', { name: /Emergency back-office/ })).toHaveAttribute(
      'href',
      '/django-admin/',
    )
  })

  it('does not offer it to a trainer or an admin who is not a superuser', async () => {
    mockApi([VIEW, 'accounts.manage_users'], { 'GET /api/v1/catalog/courses/': [] })
    renderAt('/')
    fireEvent.click(await screen.findByRole('button', { name: 'Account menu' }))
    expect(screen.queryByRole('link', { name: /back-office/i })).not.toBeInTheDocument()
  })
})

describe('Learners', () => {
  const routes = (handler?: Handler) => ({
    'GET /api/v1/admin/results/courses/': COURSES,
    'GET /api/v1/admin/results/learners/': handler ?? (() => ({ body: page(LEARNERS) })),
  })

  it('lists learners with their numbers, linking to each one', async () => {
    mockApi([VIEW], routes())
    renderAt('/admin/results/learners')
    const link = await screen.findByRole('link', { name: /Ann Ames/ })
    expect(link).toHaveAttribute('href', '/admin/results/learners/11')
    const row = link.closest('tr')!
    expect(row).toHaveTextContent('2')
    expect(row).toHaveTextContent('3')
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(3)
  })

  it('searches after the typing settles, back from page one', async () => {
    const calls = mockApi([VIEW], routes())
    renderAt('/admin/results/learners')
    await screen.findByRole('link', { name: /Ann Ames/ })
    fireEvent.change(screen.getByLabelText('Search learners'), { target: { value: 'ames' } })
    await waitFor(() =>
      expect(
        calls.some((c) => c.path.endsWith('/results/learners/') && c.query.get('search') === 'ames'),
      ).toBe(true),
    )
  })

  it('filters by course and points the export at the same course', async () => {
    const calls = mockApi([VIEW], routes())
    renderAt('/admin/results/learners')
    await screen.findByRole('link', { name: /Ann Ames/ })
    expect(screen.getByRole('link', { name: 'Export CSV' })).toHaveAttribute(
      'href',
      '/api/v1/admin/results/export/',
    )
    await screen.findByRole('option', { name: 'Escalations' })
    fireEvent.change(screen.getByLabelText('Course'), { target: { value: '2' } })
    await waitFor(() =>
      expect(calls.some((c) => c.query.get('course') === '2' && c.path.endsWith('/learners/'))).toBe(true),
    )
    expect(screen.getByRole('link', { name: 'Export CSV' })).toHaveAttribute(
      'href',
      '/api/v1/admin/results/export/?course=2',
    )
  })

  it('sorts from the column header', async () => {
    const calls = mockApi([VIEW], routes())
    renderAt('/admin/results/learners')
    await screen.findByRole('link', { name: /Ann Ames/ })
    fireEvent.click(screen.getByRole('button', { name: 'Quiz attempts' }))
    await waitFor(() => expect(calls.some((c) => c.query.get('ordering') === 'attempts')).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Quiz attempts' }))
    await waitFor(() => expect(calls.some((c) => c.query.get('ordering') === '-attempts')).toBe(true))
  })

  it('pages through the results', async () => {
    const calls = mockApi(
      [VIEW],
      routes((c) => ({
        body:
          c.query.get('page') === '2'
            ? page([LEARNERS[1]], { page: 2, pages: 2, count: 3 })
            : page([LEARNERS[0]], { pages: 2, count: 3 }),
      })),
    )
    renderAt('/admin/results/learners')
    await screen.findByRole('link', { name: /Ann Ames/ })
    expect(screen.getByText(/3 in total · page 1 of 2/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByText(/page 2 of 2/)).toBeInTheDocument()
    expect(calls.some((c) => c.query.get('page') === '2')).toBe(true)
  })

  it('says so when nothing matches, and when nobody has started', async () => {
    mockApi([VIEW], routes(() => ({ body: page([]) })))
    renderAt('/admin/results/learners')
    expect(await screen.findByText('Nobody has started a course yet.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search learners'), { target: { value: 'zzz' } })
    expect(await screen.findByText('No learners match.')).toBeInTheDocument()
  })

  it('shows a retry when the list cannot load', async () => {
    mockApi([VIEW], routes(() => ({ status: 500, body: { detail: 'Boom.' } })))
    renderAt('/admin/results/learners')
    expect(await screen.findByRole('alert')).toHaveTextContent('Couldn’t load learners')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('Learner detail', () => {
  const base = {
    'GET /api/v1/admin/results/learners/11/': { body: DETAIL },
  }

  it('shows each course, lessons done, every activity and each attempt’s score', async () => {
    mockApi([VIEW], base)
    renderAt('/admin/results/learners/11')
    expect(await screen.findByRole('heading', { name: 'Ann Ames' })).toBeInTheDocument()
    expect(screen.getByText('2 of 3 lessons completed')).toBeInTheDocument()
    expect(screen.getByText('Read')).toBeInTheDocument() // the reading, completed
    expect(screen.getAllByText('Not passed').length).toBeGreaterThan(0)
    expect(screen.getByText('Best 50%')).toBeInTheDocument()
    expect(screen.getByText('2 of 2 attempts')).toBeInTheDocument()
    const attempts = screen.getByRole('list', { name: 'Attempts at Sources quiz' })
    expect(within(attempts).getAllByRole('listitem')).toHaveLength(2)
    expect(attempts).toHaveTextContent('0%')
    expect(attempts).toHaveTextContent('50%')
  })

  it('does not offer a reset to someone who may only view', async () => {
    mockApi([VIEW], base)
    renderAt('/admin/results/learners/11')
    await screen.findByText('Best 50%')
    expect(screen.queryByRole('button', { name: 'Reset attempts' })).not.toBeInTheDocument()
  })

  it('asks first, then resets, then shows the fresh state', async () => {
    let reset = false
    const calls = mockApi([VIEW, MANAGE], {
      'GET /api/v1/admin/results/learners/11/': () => ({
        body: reset
          ? {
              ...DETAIL,
              courses: [
                {
                  ...DETAIL.courses[0],
                  activities: DETAIL.courses[0].activities.map((a) =>
                    a.scored ? { ...a, attempts: [], best_score: null, state: 'not_started' } : a,
                  ),
                },
              ],
            }
          : DETAIL,
      }),
      'DELETE /api/v1/admin/results/learners/11/activities/6/attempts/': () => {
        reset = true
        return { status: 204 }
      },
    })
    renderAt('/admin/results/learners/11')
    fireEvent.click(await screen.findByRole('button', { name: 'Reset attempts' }))

    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('Ann Ames’s 2 attempts at “Sources quiz”')
    expect(dialog).toHaveTextContent('recorded in the audit log')
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)

    fireEvent.click(within(dialog).getByRole('button', { name: 'Reset attempts' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    await waitFor(() => expect(screen.queryByText('Best 50%')).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Reset attempts' })).not.toBeInTheDocument()
    expect(screen.getByText('Not started')).toBeInTheDocument()
  })

  it('cancelling leaves everything alone', async () => {
    const calls = mockApi([VIEW, MANAGE], base)
    renderAt('/admin/results/learners/11')
    fireEvent.click(await screen.findByRole('button', { name: 'Reset attempts' }))
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancel' }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    expect(screen.getByText('Best 50%')).toBeInTheDocument()
  })

  it('shows the server’s reason when a reset is refused', async () => {
    mockApi([VIEW, MANAGE], {
      ...base,
      'DELETE /api/v1/admin/results/learners/11/activities/6/attempts/': {
        status: 403,
        body: { detail: 'You do not have permission to perform this action.' },
      },
    })
    renderAt('/admin/results/learners/11')
    fireEvent.click(await screen.findByRole('button', { name: 'Reset attempts' }))
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Reset attempts' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have permission')
  })

  it('handles an unknown learner', async () => {
    mockApi([VIEW], {})
    renderAt('/admin/results/learners/99')
    expect(await screen.findByText('Learner not found')).toBeInTheDocument()
  })

  it('says so when the learner has not started anything', async () => {
    mockApi([VIEW], { 'GET /api/v1/admin/results/learners/11/': { body: { ...DETAIL, courses: [] } } })
    renderAt('/admin/results/learners/11')
    expect(await screen.findByText('Ann Ames hasn’t started a course yet.')).toBeInTheDocument()
  })
})

describe('Quizzes', () => {
  const QUIZ = {
    id: 6,
    title: 'Sources quiz',
    course: 'CX Onboarding',
    course_id: 1,
    version: 1,
    lesson: 'Pipelines',
    required: true,
    learners: 4,
    passed: 2,
    not_passed: 1,
    in_progress: 1,
    average_best_score: 0.625,
  }

  it('summarises each quiz and links to its learners', async () => {
    mockApi([VIEW], {
      'GET /api/v1/admin/results/courses/': COURSES,
      'GET /api/v1/admin/results/quizzes/': { body: page([QUIZ]) },
    })
    renderAt('/admin/results/quizzes')
    const link = await screen.findByRole('link', { name: /Sources quiz/ })
    expect(link).toHaveAttribute('href', '/admin/results/quizzes/6')
    const row = link.closest('tr')!
    expect(row).toHaveTextContent('CX Onboarding · Pipelines')
    expect(row).toHaveTextContent('63%')
  })

  it('lists who tried a quiz, with their state and best score', async () => {
    mockApi([VIEW], {
      'GET /api/v1/admin/results/quizzes/6/': {
        body: {
          id: 6,
          title: 'Sources quiz',
          course: 'CX Onboarding',
          version: 1,
          lesson: 'Pipelines',
          max_attempts: 2,
          learners: [
            { user_id: 11, name: 'Ann Ames', email: 'ann@example.com', state: 'completed', attempts: 2, best_score: 1, last_score: 1, last_attempt_at: '2026-10-21T10:00:00Z' },
            { user_id: 12, name: 'bob@example.com', email: 'bob@example.com', state: 'exhausted', attempts: 2, best_score: 0.5, last_score: 0.5, last_attempt_at: '2026-10-21T10:00:00Z' },
          ],
        },
      },
    })
    renderAt('/admin/results/quizzes/6')
    expect(await screen.findByRole('heading', { name: 'Sources quiz' })).toBeInTheDocument()
    const ann = screen.getByRole('link', { name: /Ann Ames/ }).closest('tr')!
    expect(ann).toHaveTextContent('Passed')
    expect(ann).toHaveTextContent('100%')
    expect(screen.getByRole('link', { name: /Ann Ames/ })).toHaveAttribute('href', '/admin/results/learners/11')
    expect(screen.getByRole('columnheader', { name: 'Attempts (of 2)' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /bob@example.com/ }).closest('tr')).toHaveTextContent('Not passed')
  })
})

describe('Audit log', () => {
  const ENTRY = {
    id: 1,
    created_at: '2026-10-21T10:00:00Z',
    actor: 'adm@example.com',
    action: 'results.reset_attempts',
    target_type: 'activity',
    target_id: '6',
    target: 'bob@example.com · Sources quiz',
    changes: { attempts_deleted: 2, previous_state: 'exhausted' },
    ip_address: '10.0.0.1',
  }

  it('shows who did what, to what, with the details', async () => {
    mockApi([AUDIT], {
      'GET /api/v1/admin/audit/': { body: page([ENTRY]) },
      'GET /api/v1/admin/audit/actions/': { body: { results: ['results.export', 'results.reset_attempts'] } },
    })
    renderAt('/admin/audit')
    const row = (await screen.findByText('adm@example.com')).closest('tr')!
    expect(row).toHaveTextContent('Reset attempts')
    expect(row).toHaveTextContent('bob@example.com · Sources quiz')
    expect(row).toHaveTextContent('attempts deleted: 2')
    expect(row).toHaveTextContent('previous state: exhausted')
  })

  it('filters by action and by search', async () => {
    const calls = mockApi([AUDIT], {
      'GET /api/v1/admin/audit/': { body: page([ENTRY]) },
      'GET /api/v1/admin/audit/actions/': { body: { results: ['results.export', 'results.reset_attempts'] } },
    })
    renderAt('/admin/audit')
    await screen.findByText('adm@example.com')
    await screen.findByRole('option', { name: 'Export' })
    fireEvent.change(screen.getByLabelText('Action'), { target: { value: 'results.export' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('action') === 'results.export')).toBe(true))
    fireEvent.change(screen.getByLabelText('Search the audit log'), { target: { value: 'bob' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('search') === 'bob')).toBe(true))
  })

  it('is honest when nothing has been logged', async () => {
    mockApi([AUDIT], {
      'GET /api/v1/admin/audit/': { body: page([]) },
      'GET /api/v1/admin/audit/actions/': { body: { results: [] } },
    })
    renderAt('/admin/audit')
    expect(await screen.findByText('Nothing has been logged yet.')).toBeInTheDocument()
  })
})
