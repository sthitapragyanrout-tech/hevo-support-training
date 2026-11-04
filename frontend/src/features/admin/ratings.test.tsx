import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { hoursText } from './format'
import { estimate } from './ratingMath'
import { mockApi, page, renderAt } from './testHelpers'

afterEach(() => vi.unstubAllGlobals())

const RATE = ['manual_sim.rate_submissions']
const MANAGE = ['manual_sim.manage_reviews']
const TRAINER = ['progress.view_results', ...RATE, ...MANAGE]

const hoursFromNow = (h: number) => new Date(Date.now() + h * 3600_000).toISOString()

const row = (over: object = {}) => ({
  id: 7,
  learner: { id: 4, name: 'Lea Learner', email: 'lea@e.com' },
  activity: { id: 14, title: 'Customer reply' },
  course: 'Support basics',
  revision: 2,
  submitted_at: '2026-10-27T10:00:00Z',
  late: true,
  review_due_at: hoursFromNow(5),
  review_overdue: false,
  route: 'pool',
  assigned_mentor: null,
  claimed_by: null,
  claimed_by_me: false,
  needs_attention: false,
  can_rate: true,
  own: false,
  ...over,
})

const queue = (rows: object[], tab = 'pool', counts = { all: 3, mine: 1, pool: 2 }) => ({
  ...page(rows),
  tab,
  counts,
})

const STATS = {
  window_days: 30,
  rated: 12,
  median_hours: 14.5,
  waiting: 3,
  waiting_overdue: 1,
  escalated: 0,
  mentors: [],
}

const CRITERIA = [
  { key: 'c1', label: 'Diagnosis', description: 'Found the cause', guidance: 'RATER NOTE: 5 = exact' },
  { key: 'c2', label: 'Tone', description: 'Kind and clear', guidance: 'RATER NOTE: 5 = warm' },
]

const revision = (over: object = {}) => ({
  id: 7,
  revision: 2,
  state: 'submitted',
  submitted_at: '2026-10-27T10:00:00Z',
  late: true,
  answer: 'Second attempt text.',
  links: ['https://docs.hevodata.com/x'],
  files: [{ id: 'f1', name: 'shot.png', type: 'image/png', size_bytes: 2048, url: '/api/v1/rated-sims/files/f1/', inline: true }],
  review_due_at: hoursFromNow(5),
  withdrawn_by: '',
  routing: 'pool',
  assigned_mentor: null,
  rating: null,
  ...over,
})

const RATING = {
  raw_score: 2.5,
  passed: false,
  comment: 'Name the root cause.',
  rated_at: '2026-10-26T10:00:00Z',
  mentor: 'Mia Mentor',
  scores: [
    { key: 'c1', label: 'Diagnosis', score: 2, max: 5, feedback: 'Too vague.' },
    { key: 'c2', label: 'Tone', score: 3, max: 5, feedback: '' },
  ],
}

const FIRST = revision({
  id: 3,
  revision: 1,
  state: 'rated',
  answer: 'First attempt text.',
  links: [],
  files: [],
  rating: RATING,
})

function thread(over: Record<string, unknown> = {}) {
  return {
    id: 7,
    revision: 2,
    state: 'submitted',
    learner: { id: 4, name: 'Lea Learner', email: 'lea@e.com' },
    activity: { id: 14, title: 'Customer reply' },
    course: 'Support basics',
    scenario: 'A pipeline stopped overnight.',
    handin: 'Your reply.',
    criteria: CRITERIA,
    pass_rule: 'You pass with an average of 3.5 out of 5 or more.',
    pass_threshold: 0.7,
    min_each: 0,
    mentor_for_course: null,
    routing: {
      route: 'pool',
      assigned_mentor: null,
      claimed_by: null,
      claimed_by_me: false,
      review_due_at: hoursFromNow(5),
      review_overdue: false,
      escalated: false,
    },
    access: { can_rate: true, reason: '', can_manage: false },
    case: {
      id: 21,
      status: 'waiting',
      due_at: null,
      due_basis: 'initial',
      overdue: false,
      needs_attention: false,
      unsuccessful: 1,
      closed_reason: '',
      close_note: '',
    },
    draft: null,
    revisions: [FIRST, revision()],
    ...over,
  }
}

const THREAD_URL = 'GET /api/v1/admin/ratings/submissions/7/'

describe('the exact estimate a rater sees', () => {
  const two = [{ key: 'a', label: 'A', description: '', guidance: '' }, { key: 'b', label: 'B', description: '', guidance: '' }]
  it('is the mean on the 1–5 scale, rounded once, half-up', () => {
    const eight = Array.from({ length: 8 }, (_, i) => ({ key: `k${i}`, label: `L${i}`, description: '', guidance: '' }))
    const scores = Object.fromEntries(eight.map((c, i) => [c.key, i === 0 ? 4 : 3])) // 25 / 8 = 3.125
    expect(estimate(scores, eight, 0.7, 0)?.raw).toBe(3.13)
  })
  it('compares with the pass mark exactly', () => {
    expect(estimate({ a: 4, b: 3 }, two, 0.7, 0)).toMatchObject({ raw: 3.5, passes: true })
    expect(estimate({ a: 3, b: 3 }, two, 0.7, 0)).toMatchObject({ raw: 3, passes: false })
  })
  it('fails a good average when a criterion is under the minimum, and names it', () => {
    expect(estimate({ a: 5, b: 2 }, two, 0.7, 3)).toMatchObject({ raw: 3.5, passes: false, below: ['B'] })
  })
  it('says nothing until every criterion is scored', () => {
    expect(estimate({ a: 5, b: null }, two, 0.7, 0)).toBeNull()
  })
})

describe('how long a review took, in words', () => {
  it('uses minutes under an hour, hours, then days', () => {
    expect(hoursText(0.02)).toBe('1 min')
    expect(hoursText(0.5)).toBe('30 min')
    expect(hoursText(14.5)).toBe('14.5 h')
    expect(hoursText(72)).toBe('3 d')
  })
})

describe('Ratings — who gets in and where they land', () => {
  it('lands a mentor on the queue, with Ratings in the rail and nothing else', async () => {
    mockApi(RATE, { 'GET /api/v1/admin/ratings/queue/': queue([]) })
    renderAt('/admin')
    expect(await screen.findByRole('heading', { name: 'Ratings' })).toBeInTheDocument()
    const rail = screen.getByRole('navigation', { name: 'Admin sections' })
    expect(within(rail).getByRole('link', { name: 'Ratings' })).toBeInTheDocument()
    expect(within(rail).queryByRole('link', { name: 'Learners' })).not.toBeInTheDocument()
    expect(within(rail).queryByRole('link', { name: 'Users' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Admin' })).toBeInTheDocument() // the top-bar door
  })

  it('refuses someone with no rating permission', async () => {
    mockApi([], {})
    renderAt('/admin/ratings')
    expect(await screen.findByText('You don’t have access to this area')).toBeInTheDocument()
  })

  it('gives a rater Mine and the pool, and gives a manager the rest', async () => {
    mockApi(RATE, { 'GET /api/v1/admin/ratings/queue/': queue([]) })
    renderAt('/admin/ratings')
    expect(await screen.findByRole('tab', { name: /Mine/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Shared pool/ })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /All waiting/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /Needs a trainer/ })).not.toBeInTheDocument()
  })

  it('a manager who does not rate starts on All waiting', async () => {
    mockApi(MANAGE, { 'GET /api/v1/admin/ratings/queue/': queue([row()], 'all'), 'GET /api/v1/admin/ratings/stats/': STATS })
    renderAt('/admin/ratings')
    expect(await screen.findByRole('tab', { name: /All waiting/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByRole('tab', { name: /Mine/ })).not.toBeInTheDocument()
  })
})

describe('Ratings — the queue', () => {
  const routes = (rows: object[], extra: Record<string, unknown> = {}) => ({
    'GET /api/v1/admin/ratings/queue/': (call: { query: URLSearchParams }) => ({
      body: queue(call.query.get('tab') === 'mine' ? [] : rows, call.query.get('tab') ?? 'mine'),
    }),
    ...extra,
  })

  it('lists who, what, when and when the review is due — overdue in words', async () => {
    mockApi(RATE, routes([row(), row({ id: 8, revision: 1, late: false, review_due_at: hoursFromNow(-30), review_overdue: true, learner: { id: 5, name: 'Omar Other', email: 'omar@e.com' } })]))
    renderAt('/admin/ratings')
    fireEvent.click(await screen.findByRole('tab', { name: /Shared pool/ }))
    expect(await screen.findByText('Lea Learner')).toBeInTheDocument()
    expect(screen.getAllByText('Support basics').length).toBe(2)
    expect(screen.getByText('handed in late')).toBeInTheDocument()
    expect(screen.getByText(/^in \d+ h$/)).toBeInTheDocument()
    expect(screen.getByText(/^overdue by \d+ h$/)).toHaveClass(/overdue/)
    expect(screen.getByRole('link', { name: /Lea Learner/ })).toHaveAttribute('href', '/admin/ratings/7')
  })

  it('says whose it is and who has it', async () => {
    mockApi(RATE, routes([
      row({ route: 'escalated', assigned_mentor: 'Mia Mentor' }),
      row({ id: 9, route: 'pool', claimed_by: 'Max Mentor' }),
      row({ id: 10, route: 'pool', claimed_by_me: true, claimed_by: 'u@example.com' }),
    ]))
    renderAt('/admin/ratings')
    fireEvent.click(await screen.findByRole('tab', { name: /Shared pool/ }))
    expect(await screen.findByText('Open to any mentor (was Mia Mentor)')).toBeInTheDocument()
    expect(screen.getByText('being rated by Max Mentor')).toBeInTheDocument()
    expect(screen.getByText('being rated by you')).toBeInTheDocument()
  })

  it('lists a manager’s own work in All, marked as theirs and not for them to rate', async () => {
    mockApi(TRAINER, {
      'GET /api/v1/admin/ratings/queue/': queue(
        [row({ id: 3, own: true, can_rate: false }), row({ id: 4 })],
        'all',
      ),
      'GET /api/v1/admin/ratings/stats/': STATS,
    })
    renderAt('/admin/ratings')
    fireEvent.click(await screen.findByRole('tab', { name: /All waiting/ }))
    expect(await screen.findByText('Your own work')).toBeInTheDocument()
    expect(screen.getByText('someone else must rate it')).toBeInTheDocument()
    expect(screen.getAllByText('Shared pool')).toHaveLength(1) // the other row, not this one
  })

  it('shows the counts on the tabs and a calm message when Mine is empty', async () => {
    mockApi(RATE, routes([row()]))
    renderAt('/admin/ratings')
    expect(await screen.findByText(/Nothing is assigned to you right now/)).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Mine (1)' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Shared pool (2)' })).toBeInTheDocument()
  })

  it('filters on the server', async () => {
    const calls = mockApi(RATE, routes([row()]))
    renderAt('/admin/ratings')
    fireEvent.click(await screen.findByLabelText('Review overdue'))
    fireEvent.click(screen.getByLabelText('Needs attention'))
    await waitFor(() => {
      const last = calls.filter((c) => c.path.endsWith('/queue/')).at(-1)!
      expect(last.query.get('overdue')).toBe('1')
      expect(last.query.get('attention')).toBe('1')
    })
  })

  it('shows trainers the turnaround and the cases that need them', async () => {
    mockApi(TRAINER, {
      'GET /api/v1/admin/ratings/queue/': (call: { query: URLSearchParams }) => ({
        body:
          call.query.get('tab') === 'cases'
            ? {
                ...page([
                  { case_id: 21, learner: { id: 4, name: 'Lea Learner', email: 'lea@e.com' }, activity: { id: 14, title: 'Customer reply' }, course: 'Support basics', status: 'not_submitted', due_at: '2026-10-01T10:00:00Z', overdue: true, revisions: 0, unsuccessful: 0, needs_attention: false },
                  { case_id: 22, learner: { id: 5, name: 'Omar Other', email: 'omar@e.com' }, activity: { id: 14, title: 'Customer reply' }, course: 'Support basics', status: 'changes_requested', due_at: null, overdue: false, revisions: 3, unsuccessful: 3, needs_attention: true },
                ]),
                tab: 'cases',
                counts: {},
              }
            : queue([]),
      }),
      'GET /api/v1/admin/ratings/stats/': STATS,
    })
    renderAt('/admin/ratings')
    expect(await screen.findByText(/Reviews took a median of 14.5 h over the last 30 days/)).toBeInTheDocument()
    expect(screen.getByText(/3 waiting · 1 overdue · 0 open to any mentor/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Needs a trainer' }))
    expect(await screen.findByText(/Overdue — /)).toBeInTheDocument()
    expect(screen.getByText('Not handed in')).toBeInTheDocument()
    expect(screen.getByText('3 reviews asked for changes')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Lea Learner/ })).toHaveAttribute('href', '/admin/results/learners/4')
    expect(screen.queryByLabelText('Review overdue')).not.toBeInTheDocument() // not for cases
  })
})

describe('Rating a submission', () => {
  const setup = (over: Record<string, unknown> = {}, caps = RATE, extra: Record<string, unknown> = {}) =>
    mockApi(caps, { [THREAD_URL]: thread(over), ...extra })

  it('shows the task, the rubric with the raters’ guidance, and the whole thread', async () => {
    setup()
    renderAt('/admin/ratings/7')
    expect(await screen.findByRole('heading', { name: 'Customer reply — revision 2' })).toBeInTheDocument()
    expect(screen.getByText('A pipeline stopped overnight.')).toBeInTheDocument()
    expect(screen.getByText(/RATER NOTE: 5 = exact/)).toBeInTheDocument()
    expect(screen.getByText(/In the shared pool: any mentor may take it\./)).toBeInTheDocument()
    expect(screen.getByText(/Revision 2/)).toBeInTheDocument()
    expect(screen.getByText('Second attempt text.')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'shot.png' })).toHaveAttribute('src', '/api/v1/rated-sims/files/f1/')
    expect(screen.getByRole('link', { name: 'https://docs.hevodata.com/x' })).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByText(/Revision 1/)).toBeInTheDocument()
    expect(screen.getByText('Too vague.')).toBeInTheDocument()
    expect(screen.getByText(/Changes requested · 2.5 \/ 5/)).toBeInTheDocument()
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })

  it('works out the average as scores are picked and says whether it passes', async () => {
    setup()
    renderAt('/admin/ratings/7')
    expect(await screen.findByText('Score every criterion to see the average.')).toBeInTheDocument()
    fireEvent.click(within(screen.getByRole('radiogroup', { name: 'Diagnosis score' })).getByLabelText('4'))
    fireEvent.click(within(screen.getByRole('radiogroup', { name: 'Tone score' })).getByLabelText('3'))
    expect(screen.getByText(/Average 3.5 \/ 5 — meets the pass mark/)).toBeInTheDocument()
    fireEvent.click(within(screen.getByRole('radiogroup', { name: 'Tone score' })).getByLabelText('2'))
    expect(screen.getByText(/Average 3 \/ 5 — does not meet the pass mark/)).toBeInTheDocument()
  })

  it('needs every score and a comment, then confirms, then sends exactly what was entered', async () => {
    const calls = setup({}, RATE, {
      'POST /api/v1/admin/ratings/submissions/7/rate/': thread({ state: 'rated', draft: null }),
    })
    renderAt('/admin/ratings/7')
    const submit = await screen.findByRole('button', { name: 'Submit rating' })
    expect(submit).toBeDisabled()
    fireEvent.click(within(screen.getByRole('radiogroup', { name: 'Diagnosis score' })).getByLabelText('5'))
    fireEvent.click(within(screen.getByRole('radiogroup', { name: 'Tone score' })).getByLabelText('4'))
    expect(submit).toBeDisabled() // still no comment
    fireEvent.change(screen.getByLabelText('Overall comment for the learner'), { target: { value: 'Great work.' } })
    fireEvent.change(screen.getByLabelText('Feedback on Tone'), { target: { value: 'Warm.' } })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)
    expect(screen.getByRole('dialog')).toHaveTextContent('A submitted rating can’t be changed.')
    fireEvent.click(screen.getByRole('button', { name: 'Submit it' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path.endsWith('/rate/'))).toBe(true))
    const sent = calls.find((c) => c.path.endsWith('/rate/'))!
    expect(sent.body).toEqual({ scores: { c1: 5, c2: 4 }, feedback: { c2: 'Warm.' }, comment: 'Great work.' })
    expect(await screen.findByText('Rating submitted.')).toBeInTheDocument()
  })

  it('keeps a draft without submitting', async () => {
    const calls = setup({}, RATE, { 'POST /api/v1/admin/ratings/submissions/7/draft/': thread() })
    renderAt('/admin/ratings/7')
    fireEvent.click(await screen.findByRole('button', { name: 'Save draft' }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/draft/'))).toBe(true))
    expect(await screen.findByText('Draft saved.')).toBeInTheDocument()
    expect(calls.some((c) => c.path.endsWith('/rate/'))).toBe(false)
  })

  it('fills in a saved draft and says whose it is when it is not yours', async () => {
    setup({ draft: { scores: { c1: 4, c2: null }, feedback: { c1: 'Nearly.' }, comment: 'Started.', by: 'Max Mentor', mine: false } })
    renderAt('/admin/ratings/7')
    expect(await screen.findByText(/A draft started by Max Mentor is filled in/)).toBeInTheDocument()
    expect(screen.getByLabelText('Overall comment for the learner')).toHaveValue('Started.')
    expect(screen.getByLabelText('Feedback on Diagnosis')).toHaveValue('Nearly.')
  })

  it('shows the server’s sentence when a rating is refused', async () => {
    setup({}, RATE, { 'POST /api/v1/admin/ratings/submissions/7/draft/': { status: 409, body: { detail: 'Another mentor is rating this one.' } } })
    renderAt('/admin/ratings/7')
    fireEvent.click(await screen.findByRole('button', { name: 'Save draft' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Another mentor is rating this one.')
  })

  it('shows no form, only the reason, when this person may not rate it', async () => {
    setup({ access: { can_rate: false, reason: 'You can’t rate your own work.', can_manage: false } })
    renderAt('/admin/ratings/7')
    expect(await screen.findByText('You can’t rate your own work.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Submit rating' })).not.toBeInTheDocument()
  })

  it('shows the outcome, not a form, once it is rated', async () => {
    setup({ state: 'rated', revisions: [FIRST, revision({ state: 'rated', rating: { ...RATING, passed: true, raw_score: 4.5 } })], access: { can_rate: false, reason: 'This submission isn’t waiting for a rating.', can_manage: false } })
    renderAt('/admin/ratings/7')
    expect(await screen.findByText(/Rated 4.5 \/ 5 by Mia Mentor — passed\./)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Submit rating' })).not.toBeInTheDocument()
  })

  it('opens to any mentor, and says so, when the review is overdue', async () => {
    setup({ routing: { ...thread().routing, escalated: true, review_overdue: true, assigned_mentor: 'Mia Mentor', review_due_at: hoursFromNow(-80) } })
    renderAt('/admin/ratings/7')
    expect(await screen.findByText(/The review is overdue, so any mentor may take it \(it was with Mia Mentor\)\./)).toBeInTheDocument()
    expect(screen.getByText(/overdue by/)).toBeInTheDocument()
  })

  it('says a submission that is not theirs does not exist', async () => {
    mockApi(RATE, { [THREAD_URL]: { status: 404, body: { detail: 'Not found.' } } })
    renderAt('/admin/ratings/7')
    expect(await screen.findByText('It doesn’t exist, or it isn’t yours to see.')).toBeInTheDocument()
  })
})

describe('What a trainer can do from the review', () => {
  const manage = { can_rate: true, reason: '', can_manage: true }

  it('offers none of it to a mentor', async () => {
    mockApi(RATE, { [THREAD_URL]: thread() })
    renderAt('/admin/ratings/7')
    await screen.findByRole('button', { name: 'Submit rating' })
    for (const name of ['Reassign…', 'Extend deadline', 'Waive', 'Close', 'Take it over']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
  })

  it('reassigns just this submission to a named mentor, or back to the pool', async () => {
    const calls = mockApi(TRAINER, {
      [THREAD_URL]: thread({ access: manage }),
      'GET /api/v1/admin/ratings/mentors/': { results: [{ id: 2, name: 'Max Mentor', email: 'max@e.com' }] },
      'POST /api/v1/admin/ratings/submissions/7/reassign/': thread({ access: manage }),
    })
    renderAt('/admin/ratings/7')
    fireEvent.click(await screen.findByRole('button', { name: 'Reassign…' }))
    const dialog = await screen.findByRole('dialog', { name: 'Reassign this review' })
    expect(await within(dialog).findByRole('option', { name: 'Max Mentor (max@e.com)' })).toBeInTheDocument()
    fireEvent.change(within(dialog).getByLabelText(/Send it to/), { target: { value: '2' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reassign' }))
    await waitFor(() => expect(calls.find((c) => c.path.endsWith('/reassign/'))?.body).toEqual({ mentor_id: 2 }))
    fireEvent.click(await screen.findByRole('button', { name: 'Reassign…' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Reassign' }))
    await waitFor(() => expect(calls.filter((c) => c.path.endsWith('/reassign/')).at(-1)?.body).toEqual({ mentor_id: null }))
  })

  it('takes over someone else’s claim and releases its own', async () => {
    const calls = mockApi(TRAINER, {
      [THREAD_URL]: thread({ access: manage, routing: { ...thread().routing, claimed_by: 'Max Mentor' } }),
      'POST /api/v1/admin/ratings/submissions/7/claim/': thread({ access: manage, routing: { ...thread().routing, claimed_by: 'u@example.com', claimed_by_me: true } }),
      'POST /api/v1/admin/ratings/submissions/7/release/': thread({ access: manage }),
    })
    renderAt('/admin/ratings/7')
    expect(await screen.findByText(/Max Mentor is rating this\./)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Take it over' }))
    expect(await screen.findByText('You have taken it over.')).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Release it' }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/release/'))).toBe(true))
  })

  it('extends a deadline only with a reason, and sends the days', async () => {
    const calls = mockApi(TRAINER, {
      [THREAD_URL]: thread({ access: manage }),
      'POST /api/v1/admin/ratings/cases/21/extend/': { case: { id: 21, status: 'waiting', due_at: null, overdue: false } },
    })
    renderAt('/admin/ratings/7')
    fireEvent.click(await screen.findByRole('button', { name: 'Extend deadline' }))
    const dialog = await screen.findByRole('dialog', { name: 'Give more time' })
    const confirm = within(dialog).getByRole('button', { name: 'Extend' })
    expect(confirm).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText('Days'), { target: { value: '5' } })
    fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: 'Was ill' } })
    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    await waitFor(() => expect(calls.find((c) => c.path.endsWith('/extend/'))?.body).toEqual({ reason: 'Was ill', days: 5 }))
  })

  it.each([
    ['Waive', 'waive', 'Waive this activity'],
    ['Close', 'close', 'Close as not passed'],
  ])('%s needs a reason and explains what it does', async (button, path, title) => {
    const calls = mockApi(TRAINER, {
      [THREAD_URL]: thread({ access: manage }),
      [`POST /api/v1/admin/ratings/cases/21/${path}/`]: { case: { id: 21, status: 'waived', due_at: null, overdue: false } },
    })
    renderAt('/admin/ratings/7')
    fireEvent.click(await screen.findByRole('button', { name: button }))
    const dialog = await screen.findByRole('dialog', { name: title })
    expect(dialog).toHaveTextContent(/never as passed|not passed/)
    fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: 'Because.' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /Waive it|Close it/ }))
    await waitFor(() => expect(calls.find((c) => c.path.endsWith(`/${path}/`))?.body).toEqual({ reason: 'Because.' }))
  })

  it('offers only Reopen on a closed case', async () => {
    mockApi(TRAINER, { [THREAD_URL]: thread({ access: manage, case: { ...thread().case, status: 'not_passed', closed_reason: 'not_passed' } }) })
    renderAt('/admin/ratings/7')
    expect(await screen.findByRole('button', { name: 'Reopen' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Waive' })).not.toBeInTheDocument()
  })

  it('shows the server’s sentence when an action is refused', async () => {
    mockApi(TRAINER, {
      [THREAD_URL]: thread({ access: manage }),
      'POST /api/v1/admin/ratings/cases/21/extend/': { status: 400, body: { detail: 'Extend by 1 to 14 days.' } },
    })
    renderAt('/admin/ratings/7')
    fireEvent.click(await screen.findByRole('button', { name: 'Extend deadline' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: 'x' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Extend' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Extend by 1 to 14 days.')
  })
})

describe('A trainer’s view of a learner’s mentor-rated work', () => {
  const learner = (rated: object) => ({
    id: 4,
    name: 'Lea Learner',
    email: 'lea@e.com',
    employee_id: null,
    courses: [
      {
        course_id: 1,
        title: 'Support basics',
        version: 1,
        state: 'published',
        lessons_total: 3,
        lessons_completed: 1,
        activities: [
          {
            id: 14,
            title: 'Customer reply',
            type: 'manual_sim',
            lesson: 'Second',
            required: true,
            state: 'started',
            scored: false,
            best_score: null,
            attempts: [],
            max_attempts: 0,
            watch: null,
            sim: null,
            rated,
          },
        ],
      },
    ],
  })
  const overview = (over: object = {}) => ({
    case_id: 21,
    status: 'changes_requested',
    revisions: 3,
    unsuccessful: 3,
    needs_attention: true,
    due_at: hoursFromNow(-48),
    due_basis: 'revision',
    overdue: true,
    last_score: 2.5,
    closed_reason: '',
    close_note: '',
    waiting: null,
    ...over,
  })

  it('shows where it stands, what needs attention, and the actions a trainer has', async () => {
    mockApi(TRAINER, { 'GET /api/v1/admin/results/learners/4/': learner(overview()) })
    renderAt('/admin/results/learners/4')
    expect(await screen.findByText('Changes requested')).toBeInTheDocument()
    expect(screen.getByText(/3 revisions · last rated 2.5 \/ 5/)).toBeInTheDocument()
    expect(screen.getByText(/Overdue — was due/)).toBeInTheDocument()
    expect(screen.getByText(/Needs attention: 3 reviews have asked for changes/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Extend deadline' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
  })

  it('links a waiting review and shows who has it', async () => {
    mockApi(TRAINER, {
      'GET /api/v1/admin/results/learners/4/': learner(overview({ status: 'waiting', needs_attention: false, overdue: false, waiting: { id: 7, review_due_at: hoursFromNow(5), review_overdue: false, escalated: false, assigned_mentor: 'Mia Mentor' } })),
    })
    renderAt('/admin/results/learners/4')
    expect(await screen.findByText(/with Mia Mentor/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the review' })).toHaveAttribute('href', '/admin/ratings/7')
  })

  it('shows the closing note and offers only Reopen', async () => {
    mockApi(TRAINER, {
      'GET /api/v1/admin/results/learners/4/': learner(overview({ status: 'not_passed', closed_reason: 'not_passed', close_note: 'Left the company', needs_attention: false, overdue: false })),
    })
    renderAt('/admin/results/learners/4')
    expect(await screen.findByText('Note: Left the company')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reopen' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Waive' })).not.toBeInTheDocument()
  })

  it('shows a result viewer who cannot manage reviews no actions', async () => {
    mockApi(['progress.view_results'], { 'GET /api/v1/admin/results/learners/4/': learner(overview()) })
    renderAt('/admin/results/learners/4')
    expect(await screen.findByText('Changes requested')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Extend deadline' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reset attempts' })).not.toBeInTheDocument()
  })
})
