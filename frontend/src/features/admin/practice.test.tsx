import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, page, renderAt } from './testHelpers'

afterEach(() => vi.unstubAllGlobals())

const AUTHOR = ['catalog.author_content']
const RESULTS = ['progress.view_results']

const ZENDESK = {
  configured: true,
  import_enabled: true,
  signoff_recorded: true,
  audited_at: '2026-10-26T09:00:00Z',
  audit: { examined: 40, accepted: 31 },
  blocked_reason: null,
  auto_approve: { on: true, setting: true, master: true },
}

const OPTIONS = {
  zendesk: ZENDESK,
  skips_allowed: 5,
  import_max: 50,
  topics: [
    { key: 'billing', label: 'billing — how events are counted' },
    { key: 'alerts', label: 'alert and notification settings — Slack' },
  ],
  personas: ['urgent', 'technical', 'non-technical', 'terse'],
  model_ready: true,
  counts: { approved: 2, draft: 1, retired: 0 },
  bank: { approved: 30, drafts: 1, target: 30, state: 'ok' },
  topup: {
    on: false,
    setting: false,
    master: true,
    count: 20,
    next_run_at: '2026-10-27T02:30:00Z',
    last_check: null,
    paused: false,
  },
}

const scenario = (over: object = {}) => ({
  id: 5,
  topic: 'billing',
  topic_label: 'billing — how events are counted',
  persona_type: 'urgent',
  issue_summary: 'How are billable events counted?',
  opening_message: 'Our usage jumped. How does Hevo count events?',
  personality_notes: 'Under pressure.',
  doc_hints: ['events', 'billing'],
  reference_answer: '',
  doc_url: '',
  status: 'draft',
  source: 'generated',
  created_by: 'ann@example.com',
  approved_by: null,
  approved_at: null,
  created_at: '2026-10-20T10:00:00Z',
  uses: 0,
  source_ticket_id: null,
  auto_approved: false,
  review_note: '',
  import_run: null,
  skips: {},
  finished: 0,
  average: null,
  ...over,
})

const LIST = page([
  scenario(),
  scenario({ id: 6, issue_summary: 'How do I invite a colleague?', topic: 'alerts', status: 'approved', approved_by: 'tina@example.com', uses: 4 }),
])

function base(extra: Record<string, unknown> = {}) {
  return {
    'GET /api/v1/admin/practice/options/': OPTIONS,
    'GET /api/v1/admin/practice/scenarios/': LIST,
    'GET /api/v1/admin/practice/imports/': { results: [] },
    ...extra,
  }
}

describe('Practice scenarios — the bank', () => {
  it('is in the Content section for authors, with the counts in plain words', async () => {
    mockApi(AUTHOR, base())
    renderAt('/admin/practice')
    expect(await screen.findByRole('heading', { name: 'Practice scenarios' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Practice scenarios' })).toHaveAttribute('href', '/admin/practice')
    expect(await screen.findByText(/2 approved · 1 to review · 0 retired/)).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Practice scenarios' })
    expect(within(table).getByText('Draft — needs review')).toBeInTheDocument()
    expect(within(table).getByText('Approved')).toBeInTheDocument()
  })

  it('is not offered to someone who may only view results, and they cannot open it', async () => {
    mockApi(RESULTS, { 'GET /api/v1/admin/results/learners/': page([]), 'GET /api/v1/admin/results/courses/': { results: [] } })
    renderAt('/admin/results/learners')
    await screen.findByRole('heading', { name: 'Learners' })
    expect(screen.queryByRole('link', { name: 'Practice scenarios' })).not.toBeInTheDocument()
  })

  it('filters by status, topic, customer type and search — on the server', async () => {
    const calls = mockApi(AUTHOR, base())
    renderAt('/admin/practice')
    await screen.findByText(/2 approved/)
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'draft' } })
    fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'billing' } })
    fireEvent.change(screen.getByLabelText('Customer type'), { target: { value: 'urgent' } })
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.path.endsWith('/practice/scenarios/') &&
            c.query.get('status') === 'draft' &&
            c.query.get('topic') === 'billing' &&
            c.query.get('persona') === 'urgent',
        ),
      ).toBe(true),
    )
  })

  it('says what to do when there is nothing yet', async () => {
    mockApi(AUTHOR, base({ 'GET /api/v1/admin/practice/scenarios/': page([]) }))
    renderAt('/admin/practice')
    expect(await screen.findByText(/generate some drafts or write one/)).toBeInTheDocument()
  })

  it('approves a draft after reading it', async () => {
    let draft = scenario()
    const calls = mockApi(
      AUTHOR,
      base({
        'GET /api/v1/admin/practice/scenarios/': () => ({ body: page([draft]) }),
        'POST /api/v1/admin/practice/scenarios/5/approve/': () => {
          draft = scenario({ status: 'approved', approved_by: 'u@example.com' })
          return { body: draft }
        },
      }),
    )
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByRole('button', { name: 'How are billable events counted?' }))
    const dialog = await screen.findByRole('dialog', { name: 'Practice scenario' })
    expect(within(dialog).getByLabelText('Opening message')).toHaveValue('Our usage jumped. How does Hevo count events?')
    expect(within(dialog).getByLabelText('Documentation keywords')).toHaveValue('events, billing')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }))
    expect(await screen.findByText('Approved — learners can now get it.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.path.endsWith('/5/approve/'))).toBe(true)
    expect(await screen.findByText(/1 approved|2 approved/)).toBeInTheDocument()
  })

  it('warns that editing an approved scenario sends it back to draft', async () => {
    const calls = mockApi(
      AUTHOR,
      base({
        'GET /api/v1/admin/practice/scenarios/': { body: page([scenario({ status: 'approved', approved_by: 'tina@example.com' })]) },
        'PATCH /api/v1/admin/practice/scenarios/5/': { body: scenario({ status: 'draft' }) },
      }),
    )
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByRole('button', { name: 'How are billable events counted?' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    fireEvent.change(within(dialog).getByLabelText('Opening message'), { target: { value: 'A reworded message.' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText(/back to draft until you approve it again/)).toBeInTheDocument()
    const patch = calls.find((c) => c.method === 'PATCH')
    expect(patch?.body).toMatchObject({ opening_message: 'A reworded message.', doc_hints: ['events', 'billing'] })
  })

  it('retires and restores', async () => {
    mockApi(
      AUTHOR,
      base({
        'GET /api/v1/admin/practice/scenarios/': page([scenario({ status: 'retired' })]),
        'POST /api/v1/admin/practice/scenarios/5/restore/': { body: scenario({ status: 'draft' }) },
      }),
    )
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByRole('button', { name: 'How are billable events counted?' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Restore' }))
    expect(await screen.findByText('Restored as a draft.')).toBeInTheDocument()
  })

  it('shows the server’s sentence when something is refused', async () => {
    mockApi(
      AUTHOR,
      base({
        'GET /api/v1/admin/practice/scenarios/': page([scenario()]),
        'PATCH /api/v1/admin/practice/scenarios/5/': { status: 400, body: { detail: 'That field can’t be empty.' } },
      }),
    )
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByRole('button', { name: 'How are billable events counted?' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('The question, in one line'), { target: { value: '' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save changes' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('That field can’t be empty.')
  })

  it('writes a new scenario as a draft', async () => {
    const calls = mockApi(AUTHOR, base({ 'POST /api/v1/admin/practice/scenarios/': { status: 201, body: scenario({ id: 9 }) } }))
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByRole('button', { name: 'New scenario' }))
    const dialog = await screen.findByRole('dialog', { name: 'New practice scenario' })
    fireEvent.change(within(dialog).getByLabelText('The question, in one line'), { target: { value: 'What is a pipeline?' } })
    fireEvent.change(within(dialog).getByLabelText('Opening message'), { target: { value: 'What is a pipeline in Hevo?' } })
    fireEvent.change(within(dialog).getByLabelText('How the customer behaves'), { target: { value: 'Curious.' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create draft' }))
    expect(await screen.findByText('Created as a draft. Review it, then approve it.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ issue_summary: 'What is a pipeline?', topic: 'source_setup' })
  })

  it('asks for drafts, explaining that nothing reaches learners unapproved', async () => {
    const calls = mockApi(
      AUTHOR,
      base({ 'POST /api/v1/admin/practice/scenarios/generate/': { status: 202, body: { detail: 'Generating 3 draft scenarios.' } } }),
    )
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByRole('button', { name: 'Generate drafts' }))
    const dialog = await screen.findByRole('dialog', { name: 'Generate draft scenarios' })
    expect(dialog).toHaveTextContent('nothing reaches a learner until you approve it')
    fireEvent.change(within(dialog).getByLabelText('How many (1–20)'), { target: { value: '3' } })
    fireEvent.change(within(dialog).getByLabelText('Topic'), { target: { value: 'billing' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Generate' }))
    expect(await screen.findByText(/Generating 3 draft scenarios/)).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/generate/'))?.body).toEqual({ count: 3, topic: 'billing' })
  })

  it('cannot generate when the model is not set up, and says so', async () => {
    mockApi(AUTHOR, base({ 'GET /api/v1/admin/practice/options/': { ...OPTIONS, model_ready: false } }))
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByRole('button', { name: 'Generate drafts' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('alert')).toHaveTextContent('language model isn’t set up')
    expect(within(dialog).getByRole('button', { name: 'Generate' })).toBeDisabled()
  })
})

const TURNS = [
  { seq: 1, role: 'customer', text: 'How do I connect MySQL?', at: '2026-10-20T10:00:00Z', action: 'open', tat_seconds: null, scores: null, job_state: 'done', job_error: '' },
  {
    seq: 2,
    role: 'intern',
    text: 'Open Sources and pick MySQL. https://docs.hevodata.com/x',
    at: '2026-10-20T10:02:00Z',
    action: '',
    tat_seconds: 120,
    scores: { communication: 4, empathy: 3, accuracy: 4, concreteness: 5, tat: 5, tat_seconds: 120, notes: { communication: 'Clear.', empathy: 'A bit curt.' }, docs_relevance: 1, flags: ['injection_suspected'] },
    job_state: 'done',
    job_error: '',
  },
]

describe('Practice ticket — the trainer’s transcript', () => {
  const transcript = {
    id: 3,
    learner: { id: 11, name: 'Ann Ames' },
    activity: { id: 9, title: 'Practice ticket' },
    state: 'finished',
    preview: false,
    repeated: true,
    abandon_reason: '',
    scenario: { issue_summary: 'How do I connect MySQL?', persona_type: 'non-technical' },
    started_at: '2026-10-20T10:00:00Z',
    finished_at: '2026-10-20T10:10:00Z',
    tokens_used: 4200,
    models: { customer: 'gpt-4o-mini', evaluator: 'gpt-4o-mini' },
    turns: TURNS,
    result: {
      score: { raw: 3.84, max: 5, scaled: 0.768 },
      pass_mark: { raw: 3.5, scaled: 0.7 },
      passed: true,
      metrics: [{ key: 'communication', label: 'Communication', raw: 4, max: 5, feedback: 'Clear.', basis: 'model_judgment' }],
      narrative: null,
      grounded: false,
      exchanges: 1,
      avg_tat_seconds: 120,
      needs_review: true,
      review_reasons: ['injection_suspected'],
      scenario_ref: { topic: 'billing', persona_type: 'urgent', issue_summary: 'x' },
    },
  }

  it('shows the conversation with each reply’s scores, reasons and flags', async () => {
    mockApi(RESULTS, { 'GET /api/v1/admin/results/sessions/3/': transcript })
    renderAt('/admin/results/sessions/3')
    expect(await screen.findByRole('heading', { name: 'How do I connect MySQL?' })).toBeInTheDocument()
    expect(screen.getByText(/Ann Ames · Practice ticket/)).toBeInTheDocument()
    expect(screen.getByText(/a scenario they had seen before/)).toBeInTheDocument()
    const scores = screen.getByRole('list', { name: 'Scores for reply 2' })
    expect(scores).toHaveTextContent('Communication 4')
    expect(scores).toHaveTextContent('Took 2 min')
    expect(scores).toHaveTextContent('injection suspected')
    expect(screen.getByText(/communication: Clear\. · empathy: A bit curt\./)).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('Worth a look: injection suspected')
    expect(screen.getByText(/customer gpt-4o-mini, scoring gpt-4o-mini · 4,200 tokens used/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /View conversation/ })).not.toBeInTheDocument()
  })

  it('is closed to someone without the right to see results', async () => {
    mockApi(AUTHOR, { 'GET /api/v1/admin/results/sessions/3/': transcript })
    renderAt('/admin/results/sessions/3')
    await waitFor(() => expect(screen.queryByText('How do I connect MySQL?')).not.toBeInTheDocument())
  })

  it('says plainly when it cannot be loaded', async () => {
    mockApi(RESULTS, { 'GET /api/v1/admin/results/sessions/3/': { status: 404, body: { detail: 'Not found.' } } })
    renderAt('/admin/results/sessions/3')
    expect(await screen.findByText('Couldn’t load this ticket')).toBeInTheDocument()
  })
})

describe('Learner results — practice tickets', () => {
  it('lists each ticket with its score and a link to the transcript', async () => {
    const detail = {
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
          lessons_total: 2,
          lessons_completed: 1,
          activities: [
            {
              id: 9,
              title: 'Practice ticket',
              type: 'bot_sim',
              lesson: 'Pipelines',
              required: true,
              state: 'completed',
              scored: false,
              best_score: null,
              attempts: [],
              max_attempts: 3,
              watch: null,
              sim: {
                best_raw: 3.84,
                finished: 2,
                average_raw: 3.37,
                skips: 1,
                required: 5,
                sessions: [
                  { id: 2, state: 'finished', started_at: '2026-10-19T10:00:00Z', raw: 2.9, passed: false, needs_review: false, reasons: [], repeated: false, abandon_reason: '', skip_reason: '' },
                  { id: 3, state: 'finished', started_at: '2026-10-20T10:00:00Z', raw: 3.84, passed: true, needs_review: true, reasons: ['injection_suspected'], repeated: true, abandon_reason: '', skip_reason: '' },
                  { id: 4, state: 'abandoned', started_at: '2026-10-21T10:00:00Z', raw: null, passed: null, needs_review: false, reasons: [], repeated: false, abandon_reason: 'too_short', skip_reason: '' },
                  { id: 5, state: 'abandoned', started_at: '2026-10-22T10:00:00Z', raw: null, passed: null, needs_review: false, reasons: [], repeated: false, abandon_reason: 'skipped', skip_reason: 'not_relevant' },
                ],
              },
            },
          ],
        },
      ],
    }
    mockApi(RESULTS, { 'GET /api/v1/admin/results/learners/11/': detail })
    renderAt('/admin/results/learners/11')
    const row = (await screen.findByText('Practice ticket')).closest('li') as HTMLElement
    expect(row).toHaveTextContent('Practice ticket')
    expect(row).toHaveTextContent('2 of 5 tickets · average 3.37 / 5')
    expect(row).toHaveTextContent('1 question skipped')
    const tickets = within(row).getByRole('list', { name: 'Practice tickets for Practice ticket' })
    const links = within(tickets).getAllByRole('link')
    expect(links.map((l) => l.getAttribute('href'))).toEqual([
      '/admin/results/sessions/2',
      '/admin/results/sessions/3',
      '/admin/results/sessions/4',
      '/admin/results/sessions/5',
    ])
    // only real tickets are numbered; a skipped question isn't a ticket
    expect(links.map((l) => l.textContent)).toEqual(['Ticket 1', 'Ticket 2', 'Ticket 3', 'Skipped question'])
    // the activity is done by finishing tickets, not by "passing"
    expect(row).toHaveTextContent('Completed')
    expect(row).not.toHaveTextContent(/\bPassed\b/)
    expect(tickets).toHaveTextContent('2.9 / 5')
    expect(tickets).toHaveTextContent('Below the pass mark')
    expect(tickets).toHaveTextContent('Above the pass mark')
    expect(tickets).toHaveTextContent('Skipped (not relevant)')
    expect(tickets).toHaveTextContent('worth a look: injection suspected')
    expect(tickets).toHaveTextContent('Ended without a score')
    expect(within(row).queryByRole('button', { name: 'Reset attempts' })).not.toBeInTheDocument()
  })
})


describe('Practice scenarios — past customer queries', () => {
  const RUN = {
    id: 4,
    state: 'done',
    state_label: 'Finished',
    requested: 10,
    topic: '',
    examined: 14,
    approved: 6,
    drafted: 2,
    duplicates: 3,
    failed: 0,
    rejected: { 'zendesk:author_not_requester': 2, 'rewrite:pii_left': 1 },
    auto_approve: true,
    error: '',
    started_by: 'ann@example.com',
    created_at: '2026-10-26T09:30:00Z',
    finished_at: '2026-10-26T09:33:00Z',
    approved_now: 6,
  }
  const ADMIN = ['catalog.author_content', 'catalog.publish_courseversion']
  const closed = { ...ZENDESK, import_enabled: false, blocked_reason: 'Importing from Zendesk is switched off until the data-protection sign-off is recorded.' }

  it('says plainly that it only reads, and what is kept', async () => {
    mockApi(ADMIN, base())
    renderAt('/admin/practice')
    const panel = await screen.findByRole('region', { name: 'Past customer queries' })
    expect(panel).toHaveTextContent('We only read — nothing is ever sent to or changed in Zendesk')
    expect(panel).toHaveTextContent('only the rewrite is kept')
    expect(panel).toHaveTextContent('Zendesk: connected. Import is ready.')
  })

  it('cannot import until the sign-off is recorded, and says why', async () => {
    mockApi(ADMIN, base({ 'GET /api/v1/admin/practice/options/': { ...OPTIONS, zendesk: closed } }))
    renderAt('/admin/practice')
    const button = await screen.findByRole('button', { name: 'Import from Zendesk' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', closed.blocked_reason)
    expect(await screen.findByText(/Import is off — Importing from Zendesk is switched off/)).toBeInTheDocument()
  })

  it('a trainer who is not an administrator cannot import', async () => {
    mockApi(AUTHOR, base())
    renderAt('/admin/practice')
    expect(await screen.findByRole('button', { name: 'Import from Zendesk' })).toBeDisabled()
    expect(screen.getByLabelText(/Approve imported questions automatically/)).toBeDisabled()
  })

  it('starts an import after explaining what the model sees', async () => {
    const calls = mockApi(
      ADMIN,
      base({ 'POST /api/v1/admin/practice/imports/': { status: 202, body: { ...RUN, state: 'queued', approved: 0, drafted: 0 } } }),
    )
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByRole('button', { name: 'Import from Zendesk' }))
    const dialog = await screen.findByRole('dialog', { name: 'Import from past customer queries' })
    expect(dialog).toHaveTextContent('names, emails, numbers and links removed first')
    expect(dialog).toHaveTextContent('The customer’s original wording is not kept')
    fireEvent.change(within(dialog).getByLabelText('How many questions (1–50)'), { target: { value: '12' } })
    fireEvent.change(within(dialog).getByLabelText('Only this topic'), { target: { value: 'billing' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Import' }))
    expect(await screen.findByText(/Import started/)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST' && c.path.endsWith('/imports/'))?.body).toEqual({
      count: 12,
      topic: 'billing',
    })
  })

  it('does not start with a count outside the limit', async () => {
    mockApi(ADMIN, base())
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByRole('button', { name: 'Import from Zendesk' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('How many questions (1–50)'), { target: { value: '51' } })
    expect(within(dialog).getByRole('button', { name: 'Import' })).toBeDisabled()
  })

  it('shows the server’s sentence when an import is refused', async () => {
    mockApi(
      ADMIN,
      base({ 'POST /api/v1/admin/practice/imports/': { status: 409, body: { detail: 'An import is already running. Wait for it to finish.' } } }),
    )
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByRole('button', { name: 'Import from Zendesk' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Import' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('An import is already running')
  })

  it('reports what an import did, with the reasons in plain words', async () => {
    mockApi(ADMIN, base({ 'GET /api/v1/admin/practice/imports/': { results: [RUN] } }))
    renderAt('/admin/practice')
    const runs = await screen.findByRole('list', { name: 'Recent imports' })
    expect(runs).toHaveTextContent('Import #4 · finished')
    expect(runs).toHaveTextContent('14 past tickets looked at · 6 approved automatically · 2 for a trainer to review · 3 duplicates left out')
    const why = within(runs).getByRole('list', { name: 'Not used in import 4' })
    expect(why).toHaveTextContent('2 not used: the first message wasn’t from the customer')
    expect(why).toHaveTextContent('1 not used: personal details couldn’t be removed from it')
  })

  it('sends a whole import back to draft, after asking', async () => {
    const calls = mockApi(
      ADMIN,
      base({
        'GET /api/v1/admin/practice/imports/': { results: [RUN] },
        'POST /api/v1/admin/practice/imports/4/revert/': { body: { ...RUN, approved_now: 0, sent_back: 6 } },
      }),
    )
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByRole('button', { name: 'Send 6 back to draft' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('Anything a person approved is left alone')
    expect(calls.some((c) => c.path.endsWith('/revert/'))).toBe(false)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Send them back' }))
    expect(await screen.findByText('Sent 6 questions from import #4 back to draft.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.path.endsWith('/imports/4/revert/'))).toBe(true)
  })

  it('shows just one import’s questions on request', async () => {
    const calls = mockApi(ADMIN, base({ 'GET /api/v1/admin/practice/imports/': { results: [RUN] } }))
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByRole('button', { name: 'Show these questions' }))
    await waitFor(() =>
      expect(calls.some((c) => c.path.endsWith('/practice/scenarios/') && c.query.get('import_run') === '4')).toBe(true),
    )
    expect(screen.getByRole('button', { name: 'Showing import #4 — show all' })).toBeInTheDocument()
  })

  it('an administrator switches automatic approval off and on again', async () => {
    const calls = mockApi(
      ADMIN,
      base({
        'PATCH /api/v1/admin/practice/settings/': { body: { on: false, setting: false, master: true } },
      }),
    )
    renderAt('/admin/practice')
    const box = await screen.findByLabelText(/Approve imported questions automatically/)
    expect(box).toBeChecked()
    expect(screen.getByText(/saved as a draft instead/)).toBeInTheDocument()
    fireEvent.click(box)
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ auto_approve_enabled: false }),
    )
  })

  it('when the server has switched it off, the console cannot turn it back on', async () => {
    const off = { ...ZENDESK, auto_approve: { on: false, setting: true, master: false } }
    mockApi(ADMIN, base({ 'GET /api/v1/admin/practice/options/': { ...OPTIONS, zendesk: off } }))
    renderAt('/admin/practice')
    const box = await screen.findByLabelText(/Approve imported questions automatically/)
    expect(box).toBeDisabled()
    expect(box).not.toBeChecked()
    expect(screen.getByText(/switched off for this server/)).toBeInTheDocument()
    expect(screen.getByText(/saved as a draft for a trainer to approve/)).toBeInTheDocument()
  })

  it('shows where each question came from and how it is doing in practice', async () => {
    const imported = scenario({
      id: 8,
      issue_summary: 'How do I connect MySQL?',
      status: 'approved',
      source: 'zendesk',
      source_ticket_id: '4411',
      auto_approved: true,
      import_run: 4,
      finished: 5,
      average: 3.42,
      skips: { unclear: 2, duplicate: 1 },
      review_note: 'Skipped as unclear by 3 learners.',
    })
    mockApi(ADMIN, base({ 'GET /api/v1/admin/practice/scenarios/': page([imported]) }))
    renderAt('/admin/practice')
    const table = await screen.findByRole('table', { name: 'Practice scenarios' })
    expect(table).toHaveTextContent('Past customer query')
    expect(table).toHaveTextContent('approved automatically')
    expect(table).toHaveTextContent('5 finished · avg 3.42 / 5')
    expect(table).toHaveTextContent('skipped: 2 unclear, 1 duplicate')
    expect(table).toHaveTextContent('Skipped as unclear by 3 learners.')
    fireEvent.click(within(table).getByRole('button', { name: 'How do I connect MySQL?' }))
    const dialog = await screen.findByRole('dialog', { name: 'Practice scenario' })
    expect(within(dialog).getByRole('list', { name: 'Where this came from' })).toHaveTextContent(
      'Past customer query (Zendesk ticket 4411) · approved automatically by the strict checks',
    )
  })

  it('has a review queue and a source filter', async () => {
    const calls = mockApi(ADMIN, base())
    renderAt('/admin/practice')
    fireEvent.click(await screen.findByLabelText('Needs attention'))
    fireEvent.change(screen.getByLabelText('From'), { target: { value: 'zendesk' } })
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.path.endsWith('/practice/scenarios/') &&
            c.query.get('attention') === '1' &&
            c.query.get('source') === 'zendesk',
        ),
      ).toBe(true),
    )
  })
})

describe('Practice scenarios — an empty or short bank, and the nightly top-up', () => {
  const ADMIN = ['catalog.author_content', 'catalog.publish_courseversion']
  const RUN = {
    id: 4,
    state: 'done',
    state_label: 'Finished',
    requested: 20,
    topic: '',
    examined: 14,
    approved: 6,
    drafted: 2,
    duplicates: 3,
    failed: 0,
    rejected: {},
    auto_approve: true,
    error: '',
    started_by: 'ann@example.com',
    trigger: 'manual',
    created_at: '2026-10-26T09:30:00Z',
    finished_at: '2026-10-26T09:33:00Z',
    approved_now: 6,
  }
  const bank = (over: object) => ({ ...OPTIONS.bank, ...over })
  const withBank = (b: object, extra: object = {}) =>
    base({ 'GET /api/v1/admin/practice/options/': { ...OPTIONS, bank: b, ...extra } })

  it('says nothing when the bank is healthy', async () => {
    mockApi(ADMIN, base())
    renderAt('/admin/practice')
    await screen.findByRole('region', { name: 'Past customer queries' })
    expect(screen.queryByRole('alert', { name: 'No practice questions' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Only \d+ approved/)).not.toBeInTheDocument()
  })

  it('warns that learners cannot start when nothing is approved, drafts first', async () => {
    mockApi(ADMIN, withBank(bank({ approved: 0, drafts: 4, state: 'empty' })))
    renderAt('/admin/practice')
    const warning = await screen.findByRole('alert', { name: 'No practice questions' })
    expect(warning).toHaveTextContent('learners can’t start practice')
    expect(warning).toHaveTextContent('4 drafts are waiting for review')
    fireEvent.click(within(warning).getByRole('button', { name: 'Review drafts' }))
    expect(screen.getByLabelText('Status')).toHaveValue('draft')
  })

  it('offers an administrator the import when there is nothing to review', async () => {
    mockApi(ADMIN, withBank(bank({ approved: 0, drafts: 0, state: 'empty' })))
    renderAt('/admin/practice')
    const warning = await screen.findByRole('alert', { name: 'No practice questions' })
    expect(within(warning).queryByRole('button', { name: 'Review drafts' })).not.toBeInTheDocument()
    fireEvent.click(within(warning).getByRole('button', { name: 'Import now' }))
    expect(await screen.findByRole('dialog', { name: 'Import from past customer queries' })).toBeInTheDocument()
  })

  it('says why importing is not possible instead of offering it', async () => {
    const closed = { ...ZENDESK, blocked_reason: 'The data-protection sign-off hasn’t been recorded yet.' }
    mockApi(ADMIN, withBank(bank({ approved: 0, drafts: 0, state: 'empty' }), { zendesk: closed }))
    renderAt('/admin/practice')
    const warning = await screen.findByRole('alert', { name: 'No practice questions' })
    expect(warning).toHaveTextContent('Importing is off — The data-protection sign-off')
    expect(within(warning).queryByRole('button', { name: 'Import now' })).not.toBeInTheDocument()
  })

  it('a trainer is told only an administrator can import', async () => {
    mockApi(AUTHOR, withBank(bank({ approved: 0, drafts: 0, state: 'empty' })))
    renderAt('/admin/practice')
    const warning = await screen.findByRole('alert', { name: 'No practice questions' })
    expect(warning).toHaveTextContent('Only an administrator can import')
    expect(within(warning).queryByRole('button', { name: 'Import now' })).not.toBeInTheDocument()
  })

  it('a short bank gets a softer note with the target', async () => {
    mockApi(ADMIN, withBank(bank({ approved: 7, state: 'low' })))
    renderAt('/admin/practice')
    expect(await screen.findByText(/Only 7 approved questions/)).toBeInTheDocument()
    expect(screen.getByText(/we aim for/)).toHaveTextContent('30')
    expect(screen.queryByRole('alert', { name: 'No practice questions' })).not.toBeInTheDocument()
  })

  it('shows the top-up as off, and an administrator switches it on', async () => {
    const calls = mockApi(
      ADMIN,
      base({ 'PATCH /api/v1/admin/practice/top-up/': { ...OPTIONS.topup, on: true, setting: true } }),
    )
    renderAt('/admin/practice')
    const box = await screen.findByLabelText(/Top up the question bank every night/)
    expect(box).not.toBeChecked()
    expect(screen.getByText(/never runs without an administrator turning it on/)).toBeInTheDocument()
    fireEvent.click(box)
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ enabled: true }))
  })

  it('a trainer cannot switch it', async () => {
    mockApi(AUTHOR, base())
    renderAt('/admin/practice')
    expect(await screen.findByLabelText(/Top up the question bank every night/)).toBeDisabled()
  })

  it('says when the server has switched it off', async () => {
    mockApi(ADMIN, base({ 'GET /api/v1/admin/practice/options/': { ...OPTIONS, topup: { ...OPTIONS.topup, master: false } } }))
    renderAt('/admin/practice')
    const box = await screen.findByLabelText(/Top up the question bank every night/)
    expect(box).toBeDisabled()
    expect(box.closest('label')).toHaveTextContent('switched off for this server')
  })

  it('shows what it will do, what it last did, and when it is paused', async () => {
    const on = {
      ...OPTIONS.topup,
      on: true,
      setting: true,
      last_check: { at: '2026-10-26T02:30:00Z', outcome: 'skipped', reason: '28 questions are waiting for a trainer to review.' },
    }
    mockApi(ADMIN, base({ 'GET /api/v1/admin/practice/options/': { ...OPTIONS, topup: on } }))
    renderAt('/admin/practice')
    expect(await screen.findByLabelText(/Top up the question bank every night/)).toBeChecked()
    expect(screen.getByText(/fewer than 30 questions are approved, up to 20 past tickets/)).toBeInTheDocument()
    expect(screen.getByText(/did nothing — 28 questions are waiting for a trainer to review/)).toBeInTheDocument()
  })

  it('a paused top-up says how to resume', async () => {
    const paused = { ...OPTIONS.topup, on: true, setting: true, paused: true }
    mockApi(ADMIN, base({ 'GET /api/v1/admin/practice/options/': { ...OPTIONS, topup: paused } }))
    renderAt('/admin/practice')
    expect(await screen.findByText(/Paused: the last few nights found nothing new/)).toBeInTheDocument()
  })

  it('labels a nightly run in the history', async () => {
    mockApi(
      ADMIN,
      base({ 'GET /api/v1/admin/practice/imports/': { results: [{ ...RUN, trigger: 'scheduled', started_by: null }] } }),
    )
    renderAt('/admin/practice')
    expect(await screen.findByText(/nightly top-up/)).toBeInTheDocument()
  })
})
