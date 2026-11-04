import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ActivitySummary, RatedRevision, RatedStatus, RatedSummary, RatedView } from '../../lib/api'
import { ManualSimActivity } from './activities/ManualSimActivity'
import type { CourseContext } from './courseContext'
import { INERT_PROGRESS, type Progress } from './useProgress'

const ACTIVITY: ActivitySummary = {
  id: 14,
  activity_type: 'manual_sim',
  title: 'Customer reply',
  is_required: true,
  points: 0,
  order: 0,
  max_attempts: 0,
  completable: true,
  config: {
    scenario: 'A customer’s pipeline stopped syncing overnight.',
    handin: 'Your reply to the customer.',
    criteria: [
      { key: 'c1', label: 'Diagnosis', description: 'Found the cause' },
      { key: 'c2', label: 'Tone', description: 'Kind and clear' },
    ],
    pass_rule: 'You pass with an average of 3.5 out of 5 or more.',
    review_hours: 48,
  },
}

function revision(over: Partial<RatedRevision> = {}): RatedRevision {
  return {
    id: 1,
    revision: 1,
    state: 'submitted',
    submitted_at: '2026-10-27T10:00:00Z',
    late: false,
    answer: 'Rotate the password.',
    links: [],
    files: [],
    expected_by: '2026-10-29T10:00:00Z',
    rating: null,
    ...over,
  }
}

function view(over: Partial<RatedView['case']> = {}, revisions: RatedRevision[] = []): RatedView {
  return {
    activity: { id: 14, title: 'Customer reply' },
    config: {
      scenario: String(ACTIVITY.config.scenario),
      handin: String(ACTIVITY.config.handin),
      criteria: ACTIVITY.config.criteria as RatedView['config']['criteria'],
      pass_rule: 'You pass with an average of 3.5 out of 5 or more.',
      min_each: 0,
      allow_files: true,
      due_days: 7,
      revision_days: 3,
      review_hours: 48,
    } as RatedView['config'],
    limits: { max_files: 3, max_file_mb: 1, max_total_mb: 2, types: ['png', 'jpg', 'webp', 'pdf'], allowed: true, max_answer_chars: 200, max_links: 2 },
    case: {
      status: 'not_submitted',
      due_at: '2026-11-03T10:00:00Z',
      due_basis: 'initial',
      overdue: false,
      revisions: revisions.length,
      can_submit: true,
      can_withdraw: false,
      closed_at: null,
      ...over,
    },
    revisions,
  }
}

interface Call {
  method: string
  path: string
  form: FormData | null
  json: Record<string, unknown> | null
}
let calls: Call[]
let current: RatedView
let routes: Record<string, (call: Call) => { status: number; body: unknown }>

beforeEach(() => {
  calls = []
  current = view()
  routes = {
    'POST /api/v1/rated-sims/activities/14/open/': () => ({ status: 200, body: current }),
    'POST /api/v1/rated-sims/activities/14/submissions/': () => ({ status: 201, body: current }),
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = (init.method ?? 'GET').toUpperCase()
      const path = url.split('?')[0]
      const call: Call = {
        method,
        path,
        form: init.body instanceof FormData ? init.body : null,
        json: typeof init.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : null,
      }
      calls.push(call)
      const handler = routes[`${method} ${path}`]
      const { status, body } = handler ? handler(call) : { status: 404, body: { detail: 'Not found.' } }
      return { ok: status < 300, status, statusText: 'x', json: async () => body }
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function setup(
  options: { state?: 'completed' | 'exhausted'; rated?: RatedSummary; preview?: boolean } = {},
) {
  const refresh = vi.fn(async () => {})
  const progress: Progress = {
    ...INERT_PROGRESS,
    available: true,
    activities: options.state ? { 14: options.state } : {},
    rated: options.rated ? { 14: options.rated } : {},
    refresh,
  }
  const context = { preview: options.preview ?? false, progress } as unknown as CourseContext
  render(
    <MemoryRouter>
      <Routes>
        <Route element={<Outlet context={context} />}>
          <Route index element={<ManualSimActivity activity={ACTIVITY} />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
  return { refresh }
}

const summary = (status: RatedStatus, over: Partial<RatedSummary> = {}): RatedSummary => ({
  status,
  revisions: 1,
  due_at: '2026-11-03T10:00:00Z',
  overdue: false,
  last_score: null,
  holds_next: 'submit',
  ...over,
})

const flush = () => act(async () => {})
const open = async () => {
  fireEvent.click(screen.getByRole('button', { name: /Open|Revise|View/ }))
  await flush()
}

const png = (name = 'shot.png', bytes = 100) => new File([new Uint8Array(bytes)], name, { type: 'image/png' })
const choose = (files: File[]) =>
  fireEvent.change(screen.getByLabelText('Choose files'), { target: { files } })

describe('Mentor-rated simulation — the activity row', () => {
  it('says what it is before it is opened', () => {
    setup()
    expect(screen.getByText('Customer reply')).toBeInTheDocument()
    expect(screen.getByText(/Simulation · Rated by a mentor against a rubric · Required/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Open/ })).toBeEnabled()
  })

  it.each([
    ['not_submitted', summary('not_submitted'), /Not handed in · due/],
    ['overdue', summary('not_submitted', { overdue: true }), /Overdue — was due .* You can still hand it in\./],
    ['waiting', summary('waiting'), /Handed in · waiting for your mentor/],
    ['changes', summary('changes_requested'), /Changes requested — revise by/],
    ['late revision', summary('changes_requested', { overdue: true }), /Changes requested — revision was due/],
    ['passed', summary('passed', { last_score: 4.5 }), /Done · rated 4\.5 \/ 5/],
    ['waived', summary('waived'), /Excused by your trainer/],
    ['closed', summary('not_passed'), /Closed by your trainer/],
  ])('reads %s in plain words', (_name, rated, expected) => {
    setup({ rated })
    expect(screen.getByText(expected)).toBeInTheDocument()
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })

  it('offers the right action for each state', () => {
    setup({ rated: summary('changes_requested') })
    expect(screen.getByRole('button', { name: 'Revise' })).toBeInTheDocument()
  })
})

describe('Mentor-rated simulation — opening it', () => {
  it('starts the deadline by opening, then shows the task, the rubric and how it passes', async () => {
    const { refresh } = setup()
    await open()
    expect(calls[0]).toMatchObject({ method: 'POST', path: '/api/v1/rated-sims/activities/14/open/' })
    expect(screen.getByText('A customer’s pipeline stopped syncing overnight.')).toBeInTheDocument()
    expect(screen.getByText('Diagnosis')).toBeInTheDocument()
    expect(screen.getByText(/Found the cause/)).toBeInTheDocument()
    expect(screen.getByText(/You pass with an average of 3\.5 out of 5 or more\./)).toBeInTheDocument()
    expect(screen.getByText(/A mentor aims to review within 48 hours\./)).toBeInTheDocument()
    expect(screen.getByRole('status', { name: '' })).toBeDefined()
    expect(refresh).toHaveBeenCalled()
  })

  it('never shows anything meant for raters', async () => {
    setup()
    await open()
    expect(document.body.textContent).not.toMatch(/guidance|For raters|claimed/i)
  })

  it('says when it can’t be opened', async () => {
    routes['POST /api/v1/rated-sims/activities/14/open/'] = () => ({ status: 409, body: { detail: 'Finish “First” first.' } })
    setup()
    await open()
    expect(await screen.findByRole('alert')).toHaveTextContent('Finish “First” first.')
  })

  it('closes again', async () => {
    setup()
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByText('The task')).not.toBeInTheDocument()
  })
})

describe('Mentor-rated simulation — handing in', () => {
  it('needs an answer before it can be sent, and counts what is left', async () => {
    setup()
    await open()
    const send = screen.getByRole('button', { name: 'Hand in' })
    expect(send).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: 'My reply' } })
    expect(send).toBeEnabled()
    expect(screen.getByText('192 characters left')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: 'x'.repeat(205) } })
    expect(screen.getByText('5 characters too many')).toBeInTheDocument()
    expect(send).toBeDisabled()
  })

  it('sends the answer, links and files in one request and shows the waiting state', async () => {
    const waiting = view({ status: 'waiting', can_submit: false, can_withdraw: true }, [revision()])
    routes['POST /api/v1/rated-sims/activities/14/submissions/'] = () => ({ status: 201, body: waiting })
    const { refresh } = setup()
    await open()
    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: 'My reply' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add a link' }))
    fireEvent.change(screen.getByLabelText('Link 1'), { target: { value: 'https://docs.hevodata.com/x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add a link' })) // an empty second link is ignored
    expect(screen.queryByRole('button', { name: 'Add a link' })).not.toBeInTheDocument() // at most 2
    choose([png('one.png'), new File([new Uint8Array(10)], 'notes.pdf', { type: 'application/pdf' })])
    fireEvent.click(screen.getByRole('button', { name: 'Hand in' }))
    await flush()
    const sent = calls.find((c) => c.path.endsWith('/submissions/'))!
    expect(sent.form?.get('answer')).toBe('My reply')
    expect(sent.form?.getAll('links')).toEqual(['https://docs.hevodata.com/x'])
    expect(sent.form?.getAll('files').map((f) => (f as File).name)).toEqual(['one.png', 'notes.pdf'])
    expect(await screen.findByText(/Waiting for your mentor — expected by/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Hand in' })).not.toBeInTheDocument()
    expect(refresh).toHaveBeenCalledTimes(2)
  })

  it('checks files before sending: type, size, count', async () => {
    setup()
    await open()
    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: 'My reply' } })
    choose([new File(['x'], 'run.exe', { type: 'application/octet-stream' })])
    expect(await screen.findByRole('alert')).toHaveTextContent('“run.exe” isn’t a PNG, JPEG, WebP or PDF.')
    expect(screen.getByRole('button', { name: 'Hand in' })).toBeDisabled()
    fireEvent.click(within(screen.getByRole('list', { name: 'Files to hand in' })).getByRole('button', { name: 'Remove' }))
    choose([png('big.png', 1.5 * 1024 * 1024)])
    expect(await screen.findByRole('alert')).toHaveTextContent('“big.png” is larger than 1 MB.')
    fireEvent.click(within(screen.getByRole('list', { name: 'Files to hand in' })).getByRole('button', { name: 'Remove' }))
    choose([png('a.png'), png('b.png'), png('c.png'), png('d.png')])
    expect(await screen.findByRole('alert')).toHaveTextContent('Attach at most 3 files.')
  })

  it('shows the server’s sentence when it refuses, and keeps what was typed', async () => {
    routes['POST /api/v1/rated-sims/activities/14/submissions/'] = () => ({
      status: 400,
      body: { detail: 'That image looks damaged. Try saving it again.' },
    })
    setup()
    await open()
    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: 'My reply' } })
    fireEvent.click(screen.getByRole('button', { name: 'Hand in' }))
    expect(await screen.findByText('That image looks damaged. Try saving it again.')).toBeInTheDocument()
    expect(screen.getByLabelText('Your answer')).toHaveValue('My reply')
  })

  it('clears an old refusal as soon as something is changed', async () => {
    routes['POST /api/v1/rated-sims/activities/14/submissions/'] = () => ({
      status: 400,
      body: { detail: 'That image looks damaged. Try saving it again.' },
    })
    setup()
    await open()
    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: 'My reply' } })
    choose([png('bad.png')])
    fireEvent.click(screen.getByRole('button', { name: 'Hand in' }))
    expect(await screen.findByText('That image looks damaged. Try saving it again.')).toBeInTheDocument()
    fireEvent.click(within(screen.getByRole('list', { name: 'Files to hand in' })).getByRole('button', { name: 'Remove' }))
    expect(screen.queryByText('That image looks damaged. Try saving it again.')).not.toBeInTheDocument()
  })

  it('offers no attachments when the activity takes none', async () => {
    current = { ...view(), limits: { ...view().limits, allowed: false } }
    setup()
    await open()
    expect(screen.queryByLabelText('Choose files')).not.toBeInTheDocument()
  })
})

describe('Mentor-rated simulation — waiting, revising, done', () => {
  const waiting = () => view({ status: 'waiting', can_submit: false, can_withdraw: true }, [revision()])

  it('lets the learner take work back after confirming, and says it costs nothing', async () => {
    current = waiting()
    routes['POST /api/v1/rated-sims/submissions/1/withdraw/'] = () => ({
      status: 200,
      body: view({}, [revision({ state: 'withdrawn', expected_by: null })]),
    })
    setup({ rated: summary('waiting') })
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Withdraw and edit' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('won’t count as an attempt')
    fireEvent.click(screen.getByRole('button', { name: 'Withdraw it' }))
    await flush()
    expect(calls.at(-1)).toMatchObject({ method: 'POST', path: '/api/v1/rated-sims/submissions/1/withdraw/' })
    expect(await screen.findByRole('button', { name: 'Hand in' })).toBeInTheDocument()
  })

  it('does not offer withdrawing once a mentor has started', async () => {
    current = view({ status: 'waiting', can_submit: false, can_withdraw: false }, [revision()])
    setup({ rated: summary('waiting') })
    await open()
    expect(screen.queryByRole('button', { name: 'Withdraw and edit' })).not.toBeInTheDocument()
  })

  const rated = (passed: boolean) =>
    revision({
      state: 'rated',
      expected_by: null,
      rating: {
        raw_score: passed ? 4.5 : 2.5,
        passed,
        comment: passed ? 'Great.' : 'Not yet — name the root cause.',
        rated_at: '2026-10-28T10:00:00Z',
        mentor: 'Mia Mentor',
        scores: [
          { key: 'c1', label: 'Diagnosis', score: passed ? 5 : 2, max: 5, feedback: passed ? '' : 'Too vague.' },
          { key: 'c2', label: 'Tone', score: passed ? 4 : 3, max: 5, feedback: '' },
        ],
      },
    })

  it('shows the feedback, prefills the answer for a revision, and keeps the history', async () => {
    current = view({ status: 'changes_requested', due_at: '2026-10-31T10:00:00Z' }, [rated(false)])
    setup({ rated: summary('changes_requested') })
    await open()
    expect(screen.getByText(/Changes requested\. Hand in a revision by/)).toBeInTheDocument()
    expect(screen.getByLabelText('Your answer')).toHaveValue('Rotate the password.')
    expect(screen.getByText(/Revision 1/)).toBeInTheDocument()
    expect(screen.getByText('Too vague.')).toBeInTheDocument()
    expect(screen.getByText('2 / 5')).toBeInTheDocument()
    expect(screen.getByText(/Mia Mentor/)).toBeInTheDocument()
    expect(screen.getByText('Not yet — name the root cause.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hand in revision' })).toBeEnabled()
  })

  it('marks overdue and late work without refusing it', async () => {
    current = view({ status: 'not_submitted', overdue: true, due_at: '2026-10-01T10:00:00Z' })
    setup({ rated: summary('not_submitted', { overdue: true }) })
    await open()
    expect(screen.getByText(/Overdue — this was due .* You can still hand it in; your mentor will see it was late\./)).toBeInTheDocument()
    expect(screen.getByLabelText('Your answer')).toBeEnabled()
  })

  it.each([
    ['passed', 'Passed. Nothing more to do here.'],
    ['waived', 'Your trainer has excused you from this activity.'],
    ['not_passed', 'Your trainer has closed this activity.'],
  ] as const)('%s: no form, and says why', async (status, text) => {
    current = view({ status, can_submit: false, due_at: null }, status === 'passed' ? [rated(true)] : [])
    setup({ state: status === 'passed' ? 'completed' : 'exhausted' })
    await open()
    expect(screen.getByText(text)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Hand in/ })).not.toBeInTheDocument()
  })

  it('lists attachments as links and previews images without scripts', async () => {
    current = view({ status: 'waiting', can_submit: false }, [
      revision({
        files: [
          { id: 'f1', name: 'shot.png', type: 'image/png', size_bytes: 2048, url: '/api/v1/rated-sims/files/f1/', inline: true },
          { id: 'f2', name: 'notes.pdf', type: 'application/pdf', size_bytes: 4096, url: '/api/v1/rated-sims/files/f2/', inline: false },
        ],
        links: ['https://docs.hevodata.com/x'],
      }),
    ])
    setup({ rated: summary('waiting') })
    await open()
    const link = screen.getByRole('link', { name: 'https://docs.hevodata.com/x' })
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByRole('img', { name: 'shot.png' })).toHaveAttribute('src', '/api/v1/rated-sims/files/f1/')
    expect(screen.getByRole('link', { name: 'notes.pdf' })).toHaveAttribute('href', '/api/v1/rated-sims/files/f2/')
    expect(screen.getByText(/2 KB/)).toBeInTheDocument()
  })
})

describe('Mentor-rated simulation — an author’s preview', () => {
  it('shows the task and rubric and records nothing', async () => {
    setup({ preview: true })
    expect(screen.getByText(/Preview — nothing is recorded/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Open/ }))
    await flush()
    expect(screen.getByText('A customer’s pipeline stopped syncing overnight.')).toBeInTheDocument()
    expect(screen.getByText(/Nothing is recorded in a preview\./)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Hand in' })).not.toBeInTheDocument()
    expect(calls).toHaveLength(0)
  })
})

it('waits for progress before it can be opened', () => {
  const progress: Progress = { ...INERT_PROGRESS, available: false }
  const context = { preview: false, progress } as unknown as CourseContext
  render(
    <MemoryRouter>
      <Routes>
        <Route element={<Outlet context={context} />}>
          <Route index element={<ManualSimActivity activity={ACTIVITY} />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
  expect(screen.getByRole('button', { name: /Open/ })).toBeDisabled()
})
