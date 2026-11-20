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
      version_id: 10,
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
          lesson_id: 201,
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
          lesson_id: 201,
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

const ENROLLED = {
  course_id: 1,
  version_id: 10,
  enrollment_id: 31,
  version: 1,
  title: 'CX Onboarding',
  group: { id: 5, name: 'L1' },
  lessons_total: 3,
  lessons_done: 2,
  lessons_awaiting_review: 0,
  required_lessons_left: 1,
  next_lesson: null,
  quiz_score: 0.5,
  modules: [
    {
      id: 101,
      title: 'Pipelines',
      lessons_total: 3,
      lessons_done: 2,
      lessons_awaiting_review: 0,
      state: 'in_progress',
      next_lesson: null,
      lessons: [
        { id: 201, title: 'Pipelines', required: true, state: 'done' },
        { id: 202, title: 'Wrap-up', required: true, state: 'not_started' },
      ],
    },
  ],
  quizzes: [
    {
      activity_id: 6,
      lesson_id: 201,
      lesson_title: 'Pipelines',
      title: 'Sources quiz',
      required: true,
      status: 'not_passed',
      attempts_used: 2,
      max_attempts: 2,
      best: 0.5,
      latest: 0.5,
    },
  ],
  practice: [],
  rated: [
    {
      activity_id: 8,
      lesson_id: 201,
      lesson_title: 'Pipelines',
      title: 'Reply to a customer',
      required: true,
      status: 'passed',
      revisions: 1,
      last_score: 4.25,
      due_at: null,
      overdue: false,
      feedback: 'Clear and kind.',
      rated_at: '2026-10-21T10:00:00Z',
    },
  ],
  certification: { enabled: false, certificate: null },
}

Object.assign(DETAIL, { enrolled: [ENROLLED], certificates: [] })

const ROWS = [
  {
    enrollment_id: 31,
    user_id: 11,
    name: 'Ann Ames',
    email: 'ann@example.com',
    employee_id: 'E11',
    course: { id: 1, title: 'CX Onboarding' },
    group: { id: 5, name: 'L1' },
    lessons_done: 2,
    lessons_total: 3,
    progress: 2 / 3,
    quiz_score: 0.5,
    course_score: 0.62,
    certificate_on: true,
    threshold: 70,
    certificate: null,
    last_activity: '2026-10-20T10:00:00Z',
  },
  {
    enrollment_id: 32,
    user_id: 12,
    name: 'bob@example.com',
    email: 'bob@example.com',
    employee_id: null,
    course: { id: 1, title: 'CX Onboarding' },
    group: null,
    lessons_done: 3,
    lessons_total: 3,
    progress: 1,
    quiz_score: null,
    course_score: null,
    certificate_on: false,
    threshold: null,
    certificate: { id: 9, code: 'ABCDEFGHJK', issued_at: '2026-10-21T10:00:00Z', score: 0.9 },
    last_activity: null,
  },
]

const dashboard = (rows: object[] = ROWS, extra: object = {}) => ({
  ...page(rows),
  totals: { learners: rows.length, enrollments: rows.length, certificates: 1, courses: 1 },
  groups: [{ id: 5, name: 'L1' }],
  ...extra,
})

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

describe('Dashboard', () => {
  const routes = (handler?: Handler) => ({
    'GET /api/v1/admin/results/courses/': COURSES,
    'GET /api/v1/admin/results/dashboard/': handler ?? (() => ({ body: dashboard() })),
  })

  it('is the first item under Results, and the old Learners list is gone from the rail', async () => {
    mockApi([VIEW], routes())
    renderAt('/admin/results/dashboard')
    const rail = await screen.findByRole('navigation', { name: 'Admin sections' })
    const items = within(rail).getAllByRole('link').map((a) => a.textContent)
    expect(items.slice(0, 2)).toEqual(['Dashboard', 'Quizzes'])
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
  })

  it('is where the Admin landing page and the old Learners link now go', async () => {
    mockApi([VIEW], routes())
    renderAt('/admin')
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    mockApi([VIEW], routes())
    renderAt('/admin/results/learners')
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
  })

  it('is not in the rail, and cannot be opened, without the right to see results', async () => {
    mockApi([AUDIT], { 'GET /api/v1/admin/audit/': page([]), 'GET /api/v1/admin/audit/actions/': { results: [] } })
    renderAt('/admin/results/dashboard')
    expect(await screen.findByText('You don’t have access to this area')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Dashboard' })).not.toBeInTheDocument()
  })

  it('lists name, emp id, course, group, progress and scores, each row opening the person', async () => {
    mockApi([VIEW], routes())
    renderAt('/admin/results/dashboard')
    const link = await screen.findByRole('link', { name: /Ann Ames/ })
    expect(link).toHaveAttribute('href', '/admin/results/learners/11?course=1')
    const ann = link.closest('tr')!
    for (const text of ['E11', 'CX Onboarding', 'L1', '2 of 3', '50%', '62%', 'pass mark 70%']) {
      expect(ann).toHaveTextContent(text)
    }
    expect(within(ann).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '2')
    const bob = screen.getByRole('link', { name: /bob@example.com/ }).closest('tr')!
    expect(bob).toHaveTextContent('Earned')
    expect(bob).toHaveTextContent('Not set up')
    const totals = screen.getByText('Certificates earned').closest('div')!
    expect(totals).toHaveTextContent('1')
  })

  it('says "Not started" for someone with nothing done, with no empty bar', async () => {
    mockApi([VIEW], routes(() => ({ body: dashboard([{ ...ROWS[0], lessons_done: 0, progress: 0 }]) })))
    renderAt('/admin/results/dashboard')
    const row = (await screen.findByRole('link', { name: /Ann Ames/ })).closest('tr')!
    expect(row).toHaveTextContent('Not started · 3 lessons')
    expect(within(row).queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('sorts by progress and quiz score from the column headers', async () => {
    const calls = mockApi([VIEW], routes())
    renderAt('/admin/results/dashboard')
    await screen.findByRole('link', { name: /Ann Ames/ })
    fireEvent.click(screen.getByRole('button', { name: 'Progress' }))
    await waitFor(() => expect(calls.some((c) => c.query.get('ordering') === 'progress')).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Progress' }))
    await waitFor(() => expect(calls.some((c) => c.query.get('ordering') === '-progress')).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Quiz score' }))
    await waitFor(() => expect(calls.some((c) => c.query.get('ordering') === 'quiz')).toBe(true))
  })

  it('sorts from a "Sort by" menu too, and every sortable header shows it can be clicked', async () => {
    const calls = mockApi([VIEW], routes())
    renderAt('/admin/results/dashboard')
    await screen.findByRole('link', { name: /Ann Ames/ })
    const menu = screen.getByLabelText('Sort by') as HTMLSelectElement
    expect(menu.value).toBe('name')
    fireEvent.change(menu, { target: { value: '-quiz' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('ordering') === '-quiz')).toBe(true))
    // A header click and the menu are one setting.
    fireEvent.click(screen.getByRole('button', { name: 'Group' }))
    await waitFor(() => expect(calls.some((c) => c.query.get('ordering') === 'group')).toBe(true))
    expect(menu.value).toBe('group')
    expect(menu).toHaveTextContent('Sort: Group, ascending')
    for (const name of ['Employee', 'Progress', 'Quiz score', 'Course score']) {
      const button = screen.getByRole('button', { name })
      expect(button).toHaveAttribute('title', `Sort by ${name.toLowerCase()}`)
      expect(button.querySelector('svg')).not.toBeNull()
    }
  })

  it('filters by search, course, group and certificate, and the export follows the filters', async () => {
    const calls = mockApi([VIEW], routes())
    renderAt('/admin/results/dashboard')
    await screen.findByRole('link', { name: /Ann Ames/ })
    fireEvent.change(screen.getByLabelText('Search people'), { target: { value: 'ames' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('search') === 'ames')).toBe(true))
    await screen.findByRole('option', { name: 'Escalations' })
    fireEvent.change(screen.getByLabelText('Course'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Group'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('Certificate'), { target: { value: 'yes' } })
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.query.get('course') === '2' &&
            c.query.get('group') === '5' &&
            c.query.get('certified') === 'yes',
        ),
      ).toBe(true),
    )
    const href = screen.getByRole('link', { name: 'Export this list' }).getAttribute('href')!
    const query = new URLSearchParams(href.split('?')[1])
    expect(query.get('export')).toBe('csv')
    expect(query.get('group')).toBe('5')
    expect(screen.getByRole('link', { name: 'Export every attempt' })).toHaveAttribute(
      'href',
      '/api/v1/admin/results/export/?course=2',
    )
  })

  it('offers "No group" as a filter', async () => {
    const calls = mockApi([VIEW], routes())
    renderAt('/admin/results/dashboard')
    await screen.findByRole('option', { name: 'L1' })
    fireEvent.change(screen.getByLabelText('Group'), { target: { value: 'none' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('group') === 'none')).toBe(true))
  })

  it('says so when nobody is enrolled, and when nothing matches', async () => {
    mockApi([VIEW], routes(() => ({ body: dashboard([]) })))
    renderAt('/admin/results/dashboard')
    expect(await screen.findByText('Nobody is enrolled on a course yet.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search people'), { target: { value: 'zzz' } })
    expect(await screen.findByText('Nobody matches.')).toBeInTheDocument()
  })

  it('shows a retry when the list cannot load', async () => {
    mockApi([VIEW], routes(() => ({ status: 500, body: { detail: 'Boom.' } })))
    renderAt('/admin/results/dashboard')
    expect(await screen.findByRole('alert')).toHaveTextContent('Couldn’t load the dashboard')
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
    const course = screen.getByRole('region', { name: 'CX Onboarding' })
    expect(within(course).getByText('2 of 3 lessons')).toBeInTheDocument()
    expect(screen.getByText(/Group L1/)).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Modules in CX Onboarding' })).toHaveTextContent(
      'In progress · 2 of 3 lessons done',
    )
    expect(screen.getByText('Read')).toBeInTheDocument() // the reading, completed
    expect(screen.getAllByText('Not passed').length).toBeGreaterThan(0)
    expect(screen.getByText('Best 50%')).toBeInTheDocument()
    expect(screen.getByText('2 of 2 attempts')).toBeInTheDocument()
    const attempts = screen.getByRole('list', { name: 'Attempts at Sources quiz' })
    expect(within(attempts).getAllByRole('listitem')).toHaveLength(2)
    expect(attempts).toHaveTextContent('0%')
    expect(attempts).toHaveTextContent('50%')
  })

  it('puts the courses and modules in a side panel, lessons jumping to their activities', async () => {
    mockApi([VIEW], base)
    renderAt('/admin/results/learners/11')
    const panel = await screen.findByRole('navigation', { name: 'Courses for Ann Ames' })
    expect(within(panel).getByRole('link', { name: /CX Onboarding/ })).toHaveAttribute(
      'href',
      '/admin/results/learners/11?course=1',
    )
    const lessons = within(panel).getByRole('list', { name: 'Lessons in Pipelines' })
    expect(within(lessons).getByRole('link', { name: 'Pipelines' })).toHaveAttribute(
      'href',
      '#lesson-201',
    )
    // A lesson with nothing to show below is plain text, not a dead link.
    expect(within(lessons).queryByRole('link', { name: 'Wrap-up' })).toBeNull()
    expect(document.getElementById('lesson-201')).toHaveTextContent('Sources quiz')
  })

  it('shows the same score tables as My progress, with the mentor’s score, then the detail', async () => {
    mockApi([VIEW], base)
    renderAt('/admin/results/learners/11')
    const quizzes = await screen.findByRole('table', { name: 'Quizzes in CX Onboarding' })
    expect(within(quizzes).getByRole('link', { name: 'Sources quiz' })).toHaveAttribute(
      'href',
      '#activity-6',
    )
    const rated = screen.getByRole('table', { name: 'Mentor-rated work in CX Onboarding' })
    expect(within(rated).getByRole('columnheader', { name: 'Score' })).toBeInTheDocument()
    expect(rated).toHaveTextContent('4.25 / 5')
    expect(rated).toHaveTextContent('Clear and kind.')
    const heading = screen.getByRole('heading', { name: 'Activities, attempts and ratings' })
    expect(
      quizzes.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('shows how much of a video was watched, and why it deserves a look', async () => {
    const withVideo = structuredClone(DETAIL)
    withVideo.courses[0].activities.push({
      id: 7,
      title: 'Ingestion walkthrough',
      type: 'video',
      lesson: 'Pipelines',
      required: true,
      state: 'started',
      scored: false,
      best_score: null,
      attempts: [],
      max_attempts: 3,
      watch: {
        watched_fraction: 0.5,
        needs_review: true,
        reasons: ['Reported more watching than real time allows', 'Played in several tabs or devices at once'],
        fidelity: 'verified',
      },
    } as never)
    mockApi([VIEW], { 'GET /api/v1/admin/results/learners/11/': { body: withVideo } })
    renderAt('/admin/results/learners/11')
    const row = (await screen.findByText('Ingestion walkthrough')).closest('li') as HTMLElement
    expect(row).toHaveTextContent('Video')
    expect(row).toHaveTextContent('Watched 50%')
    expect(row).toHaveTextContent(
      'Worth a look: reported more watching than real time allows; played in several tabs or devices at once',
    )
    expect(within(row).queryByRole('button', { name: 'Reset attempts' })).not.toBeInTheDocument()
  })

  it('shows a Google Drive video as confirmed by the learner, with no percentage', async () => {
    const drive = structuredClone(DETAIL)
    drive.courses[0].activities.push({
      id: 7,
      title: 'Drive walkthrough',
      type: 'video',
      lesson: 'Pipelines',
      required: true,
      state: 'completed',
      scored: false,
      best_score: null,
      attempts: [],
      max_attempts: 3,
      watch: { watched_fraction: null, needs_review: false, reasons: [], fidelity: 'self_reported' },
    } as never)
    mockApi([VIEW], { 'GET /api/v1/admin/results/learners/11/': { body: drive } })
    renderAt('/admin/results/learners/11')
    const row = (await screen.findByText('Drive walkthrough')).closest('li') as HTMLElement
    expect(row).toHaveTextContent('Confirmed by the learner')
    expect(row).not.toHaveTextContent('%')
  })

  it('does not flag a clean video', async () => {
    const clean = structuredClone(DETAIL)
    clean.courses[0].activities.push({
      id: 7,
      title: 'Walkthrough',
      type: 'video',
      lesson: 'Pipelines',
      required: true,
      state: 'completed',
      scored: false,
      best_score: null,
      attempts: [],
      max_attempts: 3,
      watch: { watched_fraction: 1, needs_review: false, reasons: [], fidelity: 'verified' },
    } as never)
    mockApi([VIEW], { 'GET /api/v1/admin/results/learners/11/': { body: clean } })
    renderAt('/admin/results/learners/11')
    const row = (await screen.findByText('Walkthrough')).closest('li') as HTMLElement
    expect(row).toHaveTextContent('Watched 100%')
    expect(row).toHaveTextContent('Watched') // the status chip
    expect(row).not.toHaveTextContent('Worth a look')
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
    expect(document.getElementById('activity-6')).toHaveTextContent('Not started')
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

  it('says so when the learner is not on a course now', async () => {
    mockApi([VIEW], {
      'GET /api/v1/admin/results/learners/11/': { body: { ...DETAIL, courses: [], enrolled: [] } },
    })
    renderAt('/admin/results/learners/11')
    expect(await screen.findByText('Ann Ames isn’t enrolled on a course right now.')).toBeInTheDocument()
  })

  it('folds work on an older version under Earlier versions, out of the current course', async () => {
    const older = { ...DETAIL.courses[0], version_id: 9, version: 0, title: 'CX Onboarding' }
    mockApi([VIEW], {
      'GET /api/v1/admin/results/learners/11/': { body: { ...DETAIL, courses: [older, DETAIL.courses[0]] } },
    })
    renderAt('/admin/results/learners/11')
    const summary = await screen.findByText(/Earlier versions and past courses \(1\)/)
    const earlier = summary.closest('details')!
    expect(earlier).not.toHaveAttribute('open')
    expect(within(earlier).getByText('2 of 3 lessons completed')).toBeInTheDocument()
  })

  it('opens the course they came from, with the others in the side panel', async () => {
    const second = { ...ENROLLED, course_id: 2, version_id: 20, enrollment_id: 32, title: 'Escalations' }
    mockApi([VIEW], {
      'GET /api/v1/admin/results/learners/11/': { body: { ...DETAIL, enrolled: [ENROLLED, second] } },
    })
    renderAt('/admin/results/learners/11?course=2')
    expect(await screen.findByRole('region', { name: 'Escalations' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'CX Onboarding' })).toBeNull()
    // The other course is one click away in the side panel.
    const panel = screen.getByRole('navigation', { name: 'Courses for Ann Ames' })
    fireEvent.click(within(panel).getByRole('link', { name: /CX Onboarding/ }))
    expect(await screen.findByRole('region', { name: 'CX Onboarding' })).toBeInTheDocument()
  })

  it('shows the course score breakdown and lets a manager revoke the certificate with a reason', async () => {
    const cert = {
      id: 9,
      code: 'ABCDEFGHJK',
      name: 'Ann Ames',
      employee_id: null,
      course_title: 'CX Onboarding',
      course_id: 1,
      issued_at: '2026-10-21T10:00:00Z',
      score: 0.9,
      threshold: 70,
      revoked: false,
      revoked_at: null,
      revoked_reason: '',
    }
    const withCert = {
      ...DETAIL,
      certificates: [cert],
      enrolled: [
        {
          ...ENROLLED,
          certification: {
            enabled: true,
            threshold: 70,
            score: 0.9,
            missing: [],
            eligible: true,
            parts: {
              quiz: { average: 0.9, scored: 2, items: 2, weight: 1 },
              practice: { average: null, scored: 0, items: 0, weight: 1 },
              rated: { average: 0.8, scored: 1, items: 1, weight: 0 },
            },
            certificate: { id: 9, code: 'ABCDEFGHJK', issued_at: cert.issued_at, score: 0.9 },
          },
        },
      ],
    }
    const calls = mockApi([VIEW, 'enrollment.manage_enrollments'], {
      'GET /api/v1/admin/results/learners/11/': { body: withCert },
      'POST /api/v1/admin/certificates/9/revoke/': { body: { ...cert, revoked: true } },
    })
    renderAt('/admin/results/learners/11')
    const panel = await screen.findByLabelText('Certificate')
    expect(panel).toHaveTextContent('Earned')
    expect(within(panel).getByRole('link', { name: 'ABCDEFGHJK' })).toHaveAttribute(
      'href',
      '/certificates/ABCDEFGHJK',
    )
    const parts = within(panel).getByRole('list', { name: 'How the course score is made up' })
    expect(parts).toHaveTextContent('Quizzes90%')
    expect(parts).toHaveTextContent('not counted')
    expect(parts).not.toHaveTextContent('Practice tickets')

    fireEvent.click(within(panel).getByRole('button', { name: 'Revoke' }))
    const dialog = await screen.findByRole('alertdialog')
    const confirm = within(dialog).getByRole('button', { name: 'Revoke' })
    expect(confirm).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: 'Copied' } })
    fireEvent.click(confirm)
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/revoke/'))?.body).toEqual({ reason: 'Copied' }),
    )
  })

  it('offers no revoke to someone who may only view results', async () => {
    const cert = {
      id: 9, code: 'ABCDEFGHJK', name: 'Ann Ames', employee_id: null, course_title: 'CX Onboarding',
      course_id: 1, issued_at: '2026-10-21T10:00:00Z', score: 0.9, threshold: 70, revoked: false,
    }
    mockApi([VIEW], {
      'GET /api/v1/admin/results/learners/11/': { body: { ...DETAIL, certificates: [cert] } },
    })
    renderAt('/admin/results/learners/11')
    await screen.findByLabelText('Certificate')
    expect(screen.queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument()
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
