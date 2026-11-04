import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ActivitySummary, SimMetric, SimResult, SimSession } from '../../lib/api'
import { SimActivity } from './activities/SimActivity'
import type { CourseContext } from './courseContext'
import { INERT_PROGRESS, type Progress } from './useProgress'

const ACTIVITY: ActivitySummary = {
  id: 9,
  activity_type: 'bot_sim',
  title: 'Practice ticket: MySQL source',
  is_required: true,
  points: 0,
  order: 0,
  max_attempts: 3,
  completable: true,
  config: {
    max_exchanges: 6,
    pass_mark: { raw: 3.5, scaled: 0.7, max: 5 },
    required_tickets: 5,
    skips_allowed: 5,
  },
}

const METRICS: SimMetric[] = [
  ['communication', 'Communication', 4, 'Clear and friendly.', 'model_judgment'],
  ['empathy', 'Empathy', 3.5, 'Acknowledge the urgency.', 'model_judgment'],
  ['tat', 'Turnaround', 5, 'Average reply time 2.0 min (excellent); ideal is within 15 min.', 'deterministic'],
  ['concreteness', 'Concreteness', 4, 'Specific steps.', 'model_judgment'],
  ['accuracy', 'Accuracy', 4, 'Answers what was asked.', 'model_judgment'],
  ['reference_docs', 'Docs referenced', 4, 'Shared a docs.hevodata.com link. Its relevance looks plausible — an AI judgment; the page itself wasn’t opened.', 'link_check+model_relevance'],
].map(([key, label, raw, feedback, basis]) => ({ key, label, raw, max: 5, feedback, basis }) as SimMetric)

function result(over: Partial<SimResult> = {}): SimResult {
  return {
    score: { raw: 3.84, max: 5, scaled: 0.768 },
    pass_mark: { raw: 3.5, scaled: 0.7 },
    passed: true,
    metrics: METRICS,
    narrative: {
      strengths: 'Clear step-by-step instructions.',
      weaknesses: 'Confirm the customer’s setup first.',
      overall: 'A solid practice session.',
    },
    grounded: false,
    exchanges: 3,
    avg_tat_seconds: 120,
    attempts_left: null,
    state: 'started',
    quota: { done: 3, required: 5 },
    ...over,
  }
}

function session(over: Partial<SimSession> = {}): SimSession {
  return {
    id: 1,
    activity_id: 9,
    state: 'open',
    preview: false,
    subject: 'How do I connect my MySQL database as a source?',
    thread: [
      { seq: 1, role: 'customer', text: 'Hello, how do I connect MySQL to Hevo?', at: '2026-01-05T09:00:00Z', kind: 'message' },
    ],
    can_reply: true,
    waiting_for_customer: false,
    failed: false,
    failed_message: '',
    exchanges: 0,
    max_exchanges: 6,
    started_at: '2026-01-05T09:00:00Z',
    customer_waiting_since: '2026-01-05T09:00:00Z',
    feedback_pending: false,
    abandoned_reason: '',
    result: null,
    ...over,
  }
}

// ---- a tiny stand-in for the server, which the tests steer by hand ----------

interface Call {
  method: string
  path: string
  body: Record<string, unknown> | null
}
let calls: Call[]
let current: SimSession
let routes: Record<string, (body: Record<string, unknown> | null) => { status: number; body: unknown }>

function serve(extra: typeof routes = {}) {
  routes = {
    'POST /api/v1/sim/activities/9/sessions/': () => ({ status: 201, body: current }),
    'POST /api/v1/sim/activities/9/preview/': () => ({ status: 201, body: { ...current, preview: true } }),
    'GET /api/v1/sim/sessions/1/': () => ({ status: 200, body: current }),
    'POST /api/v1/sim/sessions/1/messages/': (body) => {
      current = {
        ...current,
        can_reply: false,
        waiting_for_customer: true,
        exchanges: current.exchanges + 1,
        thread: [
          ...current.thread,
          { seq: current.thread.length + 1, role: 'intern', text: String(body?.text), at: '2026-01-05T09:02:00Z', kind: 'message', status: 'sending' },
        ],
      }
      return { status: 202, body: current }
    },
    'POST /api/v1/sim/sessions/1/finish/': () => ({ status: 202, body: current }),
    'POST /api/v1/sim/sessions/1/retry/': () => ({ status: 200, body: current }),
    'POST /api/v1/sim/sessions/1/skip/': () => {
      current = { ...current, state: 'abandoned', can_reply: false, abandoned_reason: 'skipped' }
      return { status: 200, body: current }
    },
    ...extra,
  }
}

const customerAnswers = (text = 'Thanks! And what about the firewall?') => {
  current = {
    ...current,
    can_reply: true,
    waiting_for_customer: false,
    thread: [
      ...current.thread.map((t) => (t.role === 'intern' ? { ...t, status: 'sent' as const } : t)),
      { seq: current.thread.length + 1, role: 'customer', text, at: '2026-01-05T09:03:00Z', kind: 'message' },
    ],
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  calls = []
  current = session()
  serve()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = (init.method ?? 'GET').toUpperCase()
      const path = url.split('?')[0]
      const body = init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
      calls.push({ method, path, body })
      const handler = routes[`${method} ${path}`]
      const { status, body: reply } = handler ? handler(body) : { status: 404, body: { detail: 'Not found.' } }
      return { ok: status < 300, status, statusText: 'x', json: async () => reply }
    }),
  )
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function setup(
  options: {
    state?: 'completed' | 'exhausted'
    summary?: { count: number; best_score: number; last_score: number; attempts_left: number | null }
    sim?: Progress['sim']
    preview?: boolean
    activity?: ActivitySummary
  } = {},
) {
  const refresh = vi.fn(async () => {})
  const progress: Progress = {
    ...INERT_PROGRESS,
    available: true,
    activities: options.state ? { 9: options.state } : {},
    attempts: options.summary ? { 9: options.summary } : {},
    sim: options.sim ?? {},
    refresh,
  }
  const context = { preview: options.preview ?? false, progress } as unknown as CourseContext
  render(
    <MemoryRouter>
      <Routes>
        <Route element={<Outlet context={context} />}>
          <Route index element={<SimActivity activity={options.activity ?? ACTIVITY} />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
  return { refresh }
}

const flush = () => act(async () => {})
const advance = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)))
const open = async (name = /Start practice/) => {
  fireEvent.click(screen.getByRole('button', { name }))
  await flush()
}
const sent = () => calls.filter((c) => c.path.endsWith('/messages/'))

describe('Practice ticket — the activity row', () => {
  const sim = (over: object = {}) => ({
    9: { live: null, last_finished: 1, skips_used: 0, average: null, ...over },
  })

  it('says what it is, how many to finish and how long — in points out of 5', () => {
    setup()
    expect(screen.getByText('Practice ticket: MySQL source')).toBeInTheDocument()
    expect(
      screen.getByText(/Practice tickets · finish 5 tickets · up to 6 replies each · Required/),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Start practice/ })).toBeEnabled()
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })

  it('shows how many are done and the average once there are some', () => {
    setup({
      summary: { count: 3, best_score: 0.9, last_score: 0.62, attempts_left: null },
      sim: sim({ average: 0.78 }),
    })
    expect(screen.getByText(/3 of 5 done · average 3.9 \/ 5/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Start next ticket/ })).toBeEnabled()
    expect(screen.queryByRole('button', { name: /Start practice/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Last result' })).toBeInTheDocument()
  })

  it('a finished quota says so and offers the last result, not another go', () => {
    setup({
      state: 'completed',
      summary: { count: 5, best_score: 0.9, last_score: 0.5, attempts_left: null },
      sim: sim({ average: 0.8 }),
    })
    expect(screen.getByText(/Done · 5 finished · average 4 \/ 5/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /View last result/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Start/ })).not.toBeInTheDocument()
    // practice, not a test: no "passed" language on the row
    expect(screen.queryByText(/passed/i)).not.toBeInTheDocument()
  })

  it('an exhausted activity is quiet and still shows the last result', () => {
    setup({
      state: 'exhausted',
      summary: { count: 3, best_score: 0.5, last_score: 0.5, attempts_left: 0 },
      sim: sim({ average: 0.5 }),
    })
    expect(screen.getByText(/All tickets used · 3 of 5 finished · average 2.5 \/ 5/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /View last result/ })).toBeInTheDocument()
  })

  it('the quota comes from the activity, not a fixed number', () => {
    setup({ activity: { ...ACTIVITY, config: { ...ACTIVITY.config, required_tickets: 2 } } })
    expect(screen.getByText(/finish 2 tickets/)).toBeInTheDocument()
  })

  it('offers to continue a ticket that is already open', () => {
    setup({ sim: { 9: { live: { id: 1, state: 'open' }, last_finished: null, skips_used: 0, average: null } } })
    expect(screen.getByRole('button', { name: /Continue/ })).toBeInTheDocument()
  })
})

describe('Practice ticket — the window', () => {
  it('opens in a window with the customer’s message and a reply box — not a new tab', async () => {
    const openTab = vi.spyOn(window, 'open')
    setup()
    await open()
    const dialog = screen.getByRole('dialog', { name: 'Practice ticket' })
    expect(within(dialog).getByText('How do I connect my MySQL database as a source?')).toBeInTheDocument()
    expect(within(dialog).getByText('Hello, how do I connect MySQL to Hevo?')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Your reply')).toBeEnabled()
    expect(within(dialog).getByText('Reply 1 of 6')).toBeInTheDocument()
    expect(openTab).not.toHaveBeenCalled()
    // nothing about the customer's type or how they're scored leaks into the page
    expect(dialog.textContent).not.toMatch(/persona|non-technical|personality/i)
  })

  it('cannot send nothing', async () => {
    setup()
    await open()
    expect(screen.getByRole('button', { name: 'Send reply' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Your reply'), { target: { value: '   ' } })
    expect(screen.getByRole('button', { name: 'Send reply' })).toBeDisabled()
  })

  it('sends a reply once, waits for the customer, then shows their answer', async () => {
    setup()
    await open()
    fireEvent.change(screen.getByLabelText('Your reply'), { target: { value: 'Open Sources and pick MySQL.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send reply' }))
    await flush()

    expect(sent()).toHaveLength(1)
    expect(sent()[0].body).toMatchObject({ text: 'Open Sources and pick MySQL.' })
    expect(String(sent()[0].body?.client_id)).toMatch(/^[0-9a-f-]{36}$/)
    expect(screen.getByText('The customer is replying…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Send reply' })).not.toBeInTheDocument()
    expect(screen.getByText('Open Sources and pick MySQL.')).toBeInTheDocument()

    customerAnswers()
    await advance(2100) // the next look at the ticket
    expect(screen.getByText('Thanks! And what about the firewall?')).toBeInTheDocument()
    expect(screen.queryByText('The customer is replying…')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Your reply')).toHaveValue('')
    expect(screen.getByText('Reply 2 of 6')).toBeInTheDocument()
  })

  it('looks often while waiting for the customer, and rarely otherwise', async () => {
    setup()
    await open()
    const polls = () => calls.filter((c) => c.method === 'GET').length
    await advance(10_000)
    expect(polls()).toBe(0) // idle at the composer: nothing to ask yet
    await advance(11_000)
    expect(polls()).toBe(1)
    fireEvent.change(screen.getByLabelText('Your reply'), { target: { value: 'An answer.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send reply' }))
    await flush()
    for (let i = 0; i < 3; i++) await advance(2_100)
    expect(polls()).toBeGreaterThanOrEqual(1 + 3) // every ~2 s while waiting
  })

  it('keeps what you wrote when sending fails, and the retry carries the same id', async () => {
    let attempt = 0
    serve({
      'POST /api/v1/sim/sessions/1/messages/': (body) => {
        attempt += 1
        if (attempt === 1) return { status: 502, body: { detail: 'Bad gateway' } }
        return routes['POST /api/v1/sim/sessions/1/messages/ ok']?.(body) ?? { status: 202, body: current }
      },
    })
    setup()
    await open()
    fireEvent.change(screen.getByLabelText('Your reply'), { target: { value: 'My careful answer.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send reply' }))
    await flush()
    expect(screen.getByRole('alert')).toHaveTextContent('Bad gateway')
    expect(screen.getByLabelText('Your reply')).toHaveValue('My careful answer.')

    fireEvent.click(screen.getByRole('button', { name: 'Send reply' }))
    await flush()
    const [first, second] = sent()
    expect(second.body?.client_id).toBe(first.body?.client_id) // the server can tell it's the same reply
  })

  it('says plainly when the customer could not reply, and lets you try again', async () => {
    current = session({
      thread: [
        ...session().thread,
        { seq: 2, role: 'intern', text: 'My answer', at: '2026-01-05T09:02:00Z', kind: 'message', status: 'failed', error: 'The customer couldn’t reply just now. Try again in a moment.' },
      ],
      can_reply: false,
      failed: true,
      failed_message: 'The customer couldn’t reply just now. Try again in a moment.',
      exchanges: 1,
    })
    setup({ sim: { 9: { live: { id: 1, state: 'open' }, last_finished: null, skips_used: 0, average: null } } })
    await open(/Continue/)
    const alert = screen.getAllByRole('alert').map((a) => a.textContent).join(' ')
    expect(alert).toContain('couldn’t reply just now')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await flush()
    expect(calls.some((c) => c.path.endsWith('/retry/'))).toBe(true)
  })

  it('closing the window keeps the ticket and refreshes progress', async () => {
    const { refresh } = setup()
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(refresh).toHaveBeenCalled()
    expect(calls.some((c) => c.path.endsWith('/finish/'))).toBe(false) // it was not ended
  })
})

describe('Practice ticket — finishing', () => {
  it('warns that too few replies will not count, then ends without an attempt', async () => {
    serve({
      'POST /api/v1/sim/sessions/1/finish/': () => {
        current = { ...current, state: 'abandoned', abandoned_reason: 'no_replies', can_reply: false }
        return { status: 202, body: current }
      },
    })
    setup()
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Finish ticket' }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('haven’t replied yet')
    expect(screen.queryByRole('button', { name: 'Finish and see my score' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Finish without a score' }))
    await flush()
    expect(screen.getByText(/didn’t count as an attempt/)).toBeInTheDocument()
  })

  it('one reply is too little to score, and it says so', async () => {
    current = session({ exchanges: 1 })
    setup({ sim: { 9: { live: { id: 1, state: 'open' }, last_finished: null, skips_used: 0, average: null } } })
    await open(/Continue/)
    fireEvent.click(screen.getByRole('button', { name: 'Finish ticket' }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('too little to score')
    // …and the button doesn't promise a score it won't give
    expect(screen.getByRole('button', { name: 'Finish without a score' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Keep going' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('two or more replies are scored, and the button says so', async () => {
    current = session({ exchanges: 3 })
    setup({ sim: { 9: { live: { id: 1, state: 'open' }, last_finished: null, skips_used: 0, average: null } } })
    await open(/Continue/)
    fireEvent.click(screen.getByRole('button', { name: 'Finish ticket' }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('scores what you’ve written so far')
    expect(screen.getByRole('button', { name: 'Finish and see my score' })).toBeInTheDocument()
  })

  it('does not say it is preparing feedback for a ticket that will not be scored', async () => {
    current = session({ exchanges: 1, state: 'finishing', can_reply: false, feedback_pending: true })
    setup({ sim: { 9: { live: { id: 1, state: 'finishing' }, last_finished: null, skips_used: 0, average: null } } })
    await open(/Continue/)
    expect(screen.getByText(/Finishing this ticket/)).toBeInTheDocument()
    expect(screen.queryByText(/Preparing your feedback/)).not.toBeInTheDocument()
  })

  it('shows "preparing your feedback" until the result is ready', async () => {
    current = session({ exchanges: 3, state: 'finishing', can_reply: false, feedback_pending: true })
    setup({ sim: { 9: { live: { id: 1, state: 'finishing' }, last_finished: null, skips_used: 0, average: null } } })
    await open(/Continue/)
    expect(screen.getByText(/Preparing your feedback/)).toBeInTheDocument()
    current = session({ exchanges: 3, state: 'finished', can_reply: false, result: result() })
    await advance(2100)
    expect(screen.queryByText(/Preparing your feedback/)).not.toBeInTheDocument()
    expect(screen.getByText(/Above the pass mark/)).toBeInTheDocument()
  })
})

describe('Practice ticket — feedback that never arrives', () => {
  it('a reply the customer could not answer, in a ticket already closing, is "still being scored", not an error to act on', async () => {
    current = session({
      exchanges: 1,
      state: 'finishing',
      can_reply: false,
      feedback_pending: true,
      thread: [
        { seq: 1, role: 'customer', text: 'Help', at: '2026-01-05T09:00:00Z', kind: 'message', status: 'sent', error: '' },
        { seq: 2, role: 'intern', text: 'yes,', at: '2026-01-05T09:02:00Z', kind: 'message', status: 'failed', error: 'The customer couldn’t reply just now. Try again in a moment.' },
      ],
    })
    setup({ sim: { 9: { live: { id: 1, state: 'finishing' }, last_finished: null, skips_used: 0, average: null } } })
    await open(/Continue/)
    expect(screen.getByText(/still being scored/)).toBeInTheDocument()
    expect(screen.queryByText(/Try again in a moment/)).not.toBeInTheDocument()
  })

  it('after a minute it stops promising "a few seconds" and says we are still trying', async () => {
    current = session({ exchanges: 3, state: 'finishing', can_reply: false, feedback_pending: true })
    setup({ sim: { 9: { live: { id: 1, state: 'finishing' }, last_finished: null, skips_used: 0, average: null } } })
    await open(/Continue/)
    expect(screen.getByText(/this usually takes a few seconds/)).toBeInTheDocument()
    await advance(90_000)
    expect(screen.getByText(/taking longer than usual/)).toBeInTheDocument()
    expect(screen.queryByText(/usually takes a few seconds/)).not.toBeInTheDocument()
  })

  it('a ticket we gave up on says so, says it did not count, and lets them start again', async () => {
    current = session({
      exchanges: 3,
      state: 'abandoned',
      can_reply: false,
      abandoned_reason: 'feedback_failed',
    })
    setup({ sim: { 9: { live: null, last_finished: null, skips_used: 0, average: null } } })
    await open(/Continue|Start/)
    expect(screen.getByText(/couldn’t prepare feedback for this ticket/)).toBeInTheDocument()
    expect(screen.getByText(/didn’t count as an attempt/)).toBeInTheDocument()
  })
})

describe('Practice ticket — the result', () => {
  async function finished(over: Partial<SimResult> = {}) {
    const complete = over.state === 'completed'
    current = session({ exchanges: 3, state: 'finished', can_reply: false, result: result(over) })
    const view = setup({
      state: complete ? 'completed' : over.attempts_left === 0 ? 'exhausted' : undefined,
      sim: { 9: { live: null, last_finished: 1, skips_used: 0, average: 0.6 } },
      summary: { count: complete ? 5 : 3, best_score: 0.768, last_score: 0.768, attempts_left: null },
    })
    await open(complete || over.attempts_left === 0 ? /View last result/ : /Last result/)
    return view
  }

  it('gives the score out of 5 beside the pass mark, with six measured bars', async () => {
    await finished()
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Above the pass mark · 3.84 / 5 · pass mark 3.5 / 5')
    const meters = within(dialog).getAllByRole('meter')
    expect(meters.map((m) => m.getAttribute('aria-label'))).toEqual([
      'Communication', 'Empathy', 'Turnaround', 'Concreteness', 'Accuracy', 'Docs referenced',
    ])
    expect(meters[1]).toHaveAttribute('aria-valuenow', '3.5')
    expect(within(dialog).getByText('Acknowledge the urgency.')).toBeInTheDocument()
    expect(dialog.textContent).not.toMatch(/\d%/) // never a percentage
  })

  it('is honest about what was checked and what is an AI’s opinion', async () => {
    await finished()
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getAllByText('AI-assessed').length).toBeGreaterThanOrEqual(4)
    expect(within(dialog).getByText('Link checked · relevance AI-assessed')).toBeInTheDocument()
    expect(dialog).toHaveTextContent('haven’t been checked against Hevo’s documentation')
    expect(dialog).toHaveTextContent('the page itself wasn’t opened')
  })

  it('shows the written feedback', async () => {
    await finished()
    expect(screen.getByText('What went well')).toBeInTheDocument()
    expect(screen.getByText('Clear step-by-step instructions.')).toBeInTheDocument()
    expect(screen.getByText('To work on')).toBeInTheDocument()
  })

  it('can show the whole conversation again', async () => {
    await finished()
    expect(screen.queryByRole('list', { name: 'Conversation' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'View conversation' }))
    expect(screen.getByRole('list', { name: 'Conversation' })).toBeInTheDocument()
  })

  it('says how many are done and how many to go, and offers the next ticket', async () => {
    await finished()
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('That’s 3 of 5 done — 2 to go')
    expect(dialog).toHaveTextContent('Each ticket is a different question')
    expect(dialog.textContent).not.toMatch(/Passed|Not passed/)
    current = session({ id: 2, subject: 'The next ticket’s question' })
    fireEvent.click(screen.getByRole('button', { name: 'Next ticket' }))
    await flush()
    expect(calls.filter((c) => c.path.endsWith('/sessions/') && c.method === 'POST')).toHaveLength(1)
    const next = screen.getByRole('dialog')
    expect(next).toHaveTextContent('The next ticket’s question')
    expect(next).not.toHaveTextContent('Above the pass mark')
  })

  it('a ticket below the pass mark still counts, and says so', async () => {
    await finished({ passed: false, score: { raw: 2.9, max: 5, scaled: 0.58 } })
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Below the pass mark · 2.9 / 5')
    expect(dialog).toHaveTextContent('below the pass mark, but it still counts')
    expect(dialog).toHaveTextContent('3 of 5 done')
  })

  it('the last ticket completes the activity and offers no more', async () => {
    await finished({ state: 'completed', quota: { done: 5, required: 5 } })
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('you’ve finished all 5 tickets, so this activity is complete')
    expect(screen.queryByRole('button', { name: 'Next ticket' })).not.toBeInTheDocument()
  })

  it('using every ticket without finishing the quota says it is over and offers nothing', async () => {
    await finished({ attempts_left: 0, quota: { done: 3, required: 5 } })
    expect(screen.getByRole('dialog')).toHaveTextContent('used all your tickets')
    expect(screen.queryByRole('button', { name: 'Next ticket' })).not.toBeInTheDocument()
  })

  it('refreshes progress when the ticket settles', async () => {
    const { refresh } = await finished()
    expect(refresh).toHaveBeenCalled()
  })
})

describe('Practice ticket — skipping a question', () => {
  const live = { 9: { live: { id: 1, state: 'open' as const }, last_finished: null, skips_used: 0, average: null } }

  it('offers it before the first reply, with the skips that are left', async () => {
    setup({ sim: { 9: { ...live[9], skips_used: 2 } } })
    await open(/Continue/)
    fireEvent.click(screen.getByRole('button', { name: 'Skip this question' }))
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveTextContent('It won’t count, and you won’t be given it again')
    expect(dialog).toHaveTextContent('You can skip 3 more questions')
  })

  it('needs a reason, then ends the question and offers the next one', async () => {
    setup({ sim: live })
    await open(/Continue/)
    fireEvent.click(screen.getByRole('button', { name: 'Skip this question' }))
    const confirm = within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Skip this question' })
    expect(confirm).toBeDisabled()
    fireEvent.click(screen.getByLabelText(/I’ve already had a question like this/))
    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    await flush()
    expect(calls.find((c) => c.path.endsWith('/skip/'))?.body).toEqual({ reason: 'duplicate' })
    expect(screen.getByRole('dialog')).toHaveTextContent('You skipped that question')
    expect(screen.getByRole('dialog')).toHaveTextContent('you won’t be given it again')
    // the next question is a *different* ticket: the window must show it, not stay on the skipped one
    current = session({ id: 2, subject: 'A different question about billing' })
    fireEvent.click(screen.getByRole('button', { name: 'Next question' }))
    await flush()
    expect(calls.filter((c) => c.path.endsWith('/sessions/') && c.method === 'POST')).toHaveLength(1)
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('A different question about billing')
    expect(dialog).not.toHaveTextContent('You skipped that question')
    expect(within(dialog).getByLabelText('Your reply')).toBeEnabled()
  })

  it('is not offered once a reply has been sent', async () => {
    current = session({ exchanges: 1 })
    setup({ sim: live })
    await open(/Continue/)
    expect(screen.queryByRole('button', { name: 'Skip this question' })).not.toBeInTheDocument()
  })

  it('is not offered when no skips are left', async () => {
    setup({ sim: { 9: { ...live[9], skips_used: 5 } } })
    await open(/Continue/)
    expect(screen.queryByRole('button', { name: 'Skip this question' })).not.toBeInTheDocument()
  })

  it('is not offered in an author’s preview', async () => {
    setup({ preview: true })
    await open(/Try it/)
    expect(screen.queryByRole('button', { name: 'Skip this question' })).not.toBeInTheDocument()
  })

  it('says why when the server refuses', async () => {
    serve({
      'POST /api/v1/sim/sessions/1/skip/': () => ({
        status: 409,
        body: { detail: 'You’ve used all 5 skips. Please answer this one.' },
      }),
    })
    setup({ sim: live })
    await open(/Continue/)
    fireEvent.click(screen.getByRole('button', { name: 'Skip this question' }))
    fireEvent.click(screen.getByLabelText(/unclear or doesn’t make sense/))
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Skip this question' }))
    await flush()
    expect(screen.getByRole('alert')).toHaveTextContent('You’ve used all 5 skips')
  })
})

describe('Practice ticket — in an author’s preview', () => {
  it('is labelled, not scored, and uses the preview endpoint', async () => {
    current = session()
    setup({ preview: true })
    expect(screen.getByRole('button', { name: /Try it \(not scored\)/ })).toBeEnabled()
    await open(/Try it/)
    expect(calls.some((c) => c.path.endsWith('/preview/'))).toBe(true)
    expect(screen.getByRole('note')).toHaveTextContent('Preview — nothing you do here is scored or recorded.')
  })

  it('shows "Preview" instead of passed or failed on the result', async () => {
    current = session({ preview: true, state: 'finished', can_reply: false, result: result({ preview: true }) })
    routes['POST /api/v1/sim/activities/9/preview/'] = () => ({ status: 201, body: current })
    setup({ preview: true })
    await open(/Try it/)
    expect(screen.getByRole('dialog')).toHaveTextContent('Preview · 3.84 / 5')
    expect(screen.getByRole('dialog')).toHaveTextContent('nothing was recorded')
    expect(screen.queryByRole('button', { name: 'Next ticket' })).not.toBeInTheDocument()
  })
})

describe('Practice ticket — refusals read as sentences', () => {
  it('no scenarios yet', async () => {
    serve({
      'POST /api/v1/sim/activities/9/sessions/': () => ({
        status: 409,
        body: { detail: 'Practice isn’t available yet — your trainer needs to approve practice scenarios.' },
      }),
    })
    setup()
    await open()
    expect(screen.getByRole('alert')).toHaveTextContent('your trainer needs to approve practice scenarios')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows the sentence under the row, not squeezed in beside the button', async () => {
    // A long sentence next to the button took the row's whole width and squashed the title
    // into a one-letter column; it belongs in the room beneath the row.
    serve({
      'POST /api/v1/sim/activities/9/preview/': () => ({
        status: 503,
        body: { detail: 'Practice isn’t set up yet. Ask an administrator to add the model key.' },
      }),
    })
    setup({ preview: true })
    await open(/Try it/)
    const alert = screen.getByRole('alert')
    const button = screen.getByRole('button', { name: /Try it/ })
    expect(alert).toHaveTextContent('Ask an administrator to add the model key')
    expect(alert.parentElement?.contains(button)).toBe(false)
    expect(screen.getByText('Practice ticket: MySQL source')).toBeInTheDocument()
  })

  it('paused', async () => {
    serve({
      'POST /api/v1/sim/activities/9/sessions/': () => ({
        status: 503,
        body: { detail: 'Practice is paused for a short while. Please try again in a few minutes.' },
      }),
    })
    setup()
    await open()
    expect(screen.getByRole('alert')).toHaveTextContent('Practice is paused')
  })

  it('a locked lesson', async () => {
    serve({
      'POST /api/v1/sim/activities/9/sessions/': () => ({ status: 409, body: { detail: 'Finish “First” first.' } }),
    })
    setup()
    await open()
    expect(screen.getByRole('alert')).toHaveTextContent('Finish “First” first.')
  })
})
