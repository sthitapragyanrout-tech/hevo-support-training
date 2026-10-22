import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from '../../App'
import { AuthProvider } from '../../lib/auth'
import { sampleCourse } from '../catalog/testData'
import type { ActivityType, AuthCourse, AuthNode } from './types'

const AUTHOR = ['catalog.author_content']
const PUBLISHER = ['catalog.author_content', 'catalog.publish_courseversion']

function user(capabilities: string[]) {
  return {
    id: 1,
    username: 'u',
    email: 'u@example.com',
    employee_id: null,
    must_change_password: false,
    roles: [],
    capabilities,
  }
}

const TYPES: ActivityType[] = [
  {
    key: 'reading',
    label: 'Reading',
    description: 'Read a page.',
    icon: 'book',
    renderer_key: 'reading',
    default_config: { source_url: '' },
    config_schema: {
      type: 'object',
      properties: {
        source_url: { type: 'string', title: 'Link to the reading' },
        estimated_read_minutes: { type: 'integer', title: 'Read time' },
      },
      required: ['source_url'],
    },
  },
  {
    key: 'mcq',
    label: 'Quiz',
    description: 'Questions.',
    icon: 'quiz',
    renderer_key: 'mcq',
    default_config: { questions: [] },
    config_schema: {
      type: 'object',
      properties: { questions: { type: 'array', title: 'Questions' } },
      required: ['questions'],
    },
  },
  {
    // A type with a structured field and no editor of its own: the generic form.
    key: 'poll',
    label: 'Poll',
    description: 'A poll.',
    icon: 'quiz',
    renderer_key: 'poll',
    default_config: { questions: [] },
    config_schema: {
      type: 'object',
      properties: { questions: { type: 'array', title: 'Questions' } },
      required: ['questions'],
    },
  },
]

function node(
  id: number,
  kind: AuthNode['kind'],
  title: string,
  extra: Partial<AuthNode> = {},
  children: AuthNode[] = [],
): AuthNode {
  return {
    id,
    kind,
    title,
    slug: title.toLowerCase(),
    description: '',
    is_required: true,
    estimated_minutes: null,
    order: 0,
    activities: [],
    children,
    ...extra,
  }
}

function course(overrides: Partial<AuthCourse> = {}): AuthCourse {
  return {
    id: 1,
    slug: 'cx',
    title: 'CX Onboarding',
    status: { key: 'draft', label: 'Draft' },
    version: { number: 1, state: 'draft', published_at: null, submitted_at: null, submitted_by: null },
    published_version: null,
    editable: true,
    actions: { start_draft: false, submit: true, publish: false, return_to_draft: false },
    tree: {
      id: 1,
      course_id: 1,
      version: 1,
      root: node(1, 'course', 'CX Onboarding', { description: 'Learn.' }, [
        node(2, 'segment', 'Fundamentals', {}, [
          node(3, 'topic', 'Pipelines', { description: 'Intro text.' }, [
            node(4, 'subtopic', 'Sources', {
              activities: [
                {
                  id: 9,
                  activity_type: 'reading',
                  title: 'Read the docs',
                  config: { source_url: '' },
                  is_required: true,
                  points: 0,
                  max_attempts: 3,
                  mastery_threshold: null,
                  order: 0,
                  needs_setup: true,
                  completable: false,
                },
              ],
            }),
          ]),
        ]),
      ]),
    },
    ...overrides,
  }
}

interface Call {
  method: string
  path: string
  body: unknown
}

type Handler = (call: Call) => { status?: number; body?: unknown }

/** Stub fetch with a `METHOD /path` table; records every call. */
function mockApi(capabilities: string[], routes: Record<string, Handler>) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = (init.method ?? 'GET').toUpperCase()
      const path = url.split('?')[0]
      const body = typeof init.body === 'string' ? JSON.parse(init.body) : init.body
      const call = { method, path, body }
      calls.push(call)
      let result: { status?: number; body?: unknown } = { status: 404, body: { detail: 'Not found.' } }
      if (path.includes('/auth/session/')) {
        result = { body: { authenticated: true, user: user(capabilities) } }
      } else if (routes[`${method} ${path}`]) {
        result = routes[`${method} ${path}`](call)
      }
      const status = result.status ?? 200
      return {
        ok: status >= 200 && status < 300,
        status,
        statusText: 'x',
        json: async () => result.body ?? {},
      }
    }),
  )
  return calls
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

const BASE = '/api/v1/authoring'

afterEach(() => vi.unstubAllGlobals())

describe('capabilities', () => {
  it('shows Studio in the nav only to people who can author', async () => {
    mockApi([], { 'GET /api/v1/catalog/courses/': () => ({ body: [] }) })
    renderAt('/')
    await screen.findByText(/No courses yet/)
    expect(screen.queryByRole('link', { name: 'Studio' })).not.toBeInTheDocument()
  })

  it('shows Studio to an author', async () => {
    mockApi(AUTHOR, { 'GET /api/v1/catalog/courses/': () => ({ body: [] }) })
    renderAt('/')
    expect(await screen.findByRole('link', { name: 'Studio' })).toHaveAttribute('href', '/studio')
  })

  it('blocks the Studio URL for someone without the capability', async () => {
    mockApi([], {})
    renderAt('/studio')
    expect(await screen.findByText(/don’t have access/i)).toBeInTheDocument()
  })

  it('gives people who manage users the Admin console, not the emergency back-office', async () => {
    mockApi(['accounts.manage_users'], { 'GET /api/v1/catalog/courses/': () => ({ body: [] }) })
    renderAt('/')
    expect(await screen.findByRole('link', { name: 'Admin' })).toHaveAttribute('href', '/admin')
    fireEvent.click(screen.getByRole('button', { name: 'Account menu' }))
    expect(screen.queryByRole('link', { name: /back-office/i })).not.toBeInTheDocument()
  })
})

describe('Studio course list', () => {
  const rows = [
    { id: 1, slug: 'a', title: 'Alpha', status: { key: 'draft', label: 'Draft' } },
    { id: 2, slug: 'b', title: 'Beta', status: { key: 'in_review', label: 'In review' } },
  ]

  it('groups courses by what happens next, and tells a publisher what is waiting', async () => {
    mockApi(PUBLISHER, { [`GET ${BASE}/courses/`]: () => ({ body: rows }) })
    renderAt('/studio')
    expect(await screen.findByRole('heading', { name: 'Waiting to be published' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'In progress' })).toBeInTheDocument()

    const waiting = screen.getByRole('link', { name: /Beta/ })
    expect(waiting).toHaveAttribute('href', '/studio/courses/2')
    expect(waiting).toHaveTextContent('In review')
    expect(waiting).toHaveTextContent('Review') // the publisher's next move
    expect(screen.getByRole('link', { name: /Alpha/ })).toHaveTextContent('Continue')
  })

  it('shows a trainer the same list without publisher framing', async () => {
    mockApi(AUTHOR, { [`GET ${BASE}/courses/`]: () => ({ body: rows }) })
    renderAt('/studio')
    expect(await screen.findByRole('heading', { name: 'With an administrator' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Waiting to be published' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Beta/ })).toHaveTextContent('View')
  })

  it('shows module and lesson counts on each row', async () => {
    mockApi(AUTHOR, {
      [`GET ${BASE}/courses/`]: () => ({
        body: [{ ...rows[0], modules: 2, lessons: 5 }, { ...rows[1], modules: 0, lessons: 0 }],
      }),
    })
    renderAt('/studio')
    expect(await screen.findByRole('link', { name: /Alpha/ })).toHaveTextContent('2 modules · 5 lessons')
    expect(screen.getByRole('link', { name: /Beta/ })).toHaveTextContent('No content yet')
  })

  it('invites the first course when there are none', async () => {
    mockApi(AUTHOR, { [`GET ${BASE}/courses/`]: () => ({ body: [] }) })
    renderAt('/studio')
    expect(await screen.findByRole('heading', { name: 'Build your first course' })).toBeInTheDocument()
  })
})

describe('Create course', () => {
  it('posts the title and lands in the curriculum builder', async () => {
    const calls = mockApi(AUTHOR, {
      [`POST ${BASE}/courses/`]: () => ({ status: 201, body: course() }),
      [`GET ${BASE}/courses/1/`]: () => ({ body: course() }),
      [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
    })
    renderAt('/studio/new')
    fireEvent.change(await screen.findByLabelText(/Course title/), { target: { value: 'My course' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create course' }))

    expect(await screen.findByRole('navigation', { name: 'Course outline' })).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST' && c.path === `${BASE}/courses/`)
    expect(post?.body).toEqual({ title: 'My course', description: '' })
  })

  it('refuses an empty title without calling the server', async () => {
    const calls = mockApi(AUTHOR, {})
    renderAt('/studio/new')
    fireEvent.click(await screen.findByRole('button', { name: 'Create course' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Give the course a title')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })
})

describe('Curriculum builder', () => {
  function builderRoutes(c: AuthCourse = course()) {
    return {
      [`GET ${BASE}/courses/1/`]: () => ({ body: c }),
      [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
    }
  }

  it('uses learner words (Module / Lesson / Section) and never the data-model names', async () => {
    mockApi(AUTHOR, builderRoutes())
    renderAt('/studio/courses/1/curriculum/3')
    const outline = await screen.findByRole('navigation', { name: 'Course outline' })
    expect(within(outline).getByText('Fundamentals')).toBeInTheDocument()
    expect(within(outline).getByRole('button', { name: 'Pipelines' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByLabelText('Lesson title')).toHaveValue('Pipelines')
    expect(screen.getByRole('region', { name: 'Section 1: Sources' })).toBeInTheDocument()
    const page = document.body.textContent ?? ''
    for (const internal of ['segment', 'subtopic', 'topic']) {
      expect(page.toLowerCase()).not.toContain(internal)
    }
  })

  it('adds a lesson under a module from context: the client sends only parent and title', async () => {
    const calls = mockApi(AUTHOR, {
      ...builderRoutes(),
      [`POST ${BASE}/courses/1/nodes/`]: () => ({
        status: 201,
        body: node(10, 'topic', 'New lesson'),
      }),
    })
    renderAt('/studio/courses/1/curriculum')
    const outline = await screen.findByRole('navigation', { name: 'Course outline' })
    fireEvent.click(within(outline).getByRole('button', { name: 'Add lesson' }))
    const input = within(outline).getByRole('textbox', { name: 'Add lesson' })
    fireEvent.change(input, { target: { value: 'New lesson' } })
    fireEvent.submit(input.closest('form')!)

    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST' && c.path.endsWith('/nodes/'))?.body).toEqual({
        parent: 2,
        title: 'New lesson',
      }),
    )
  })

  it('hides every editing control when the course is locked', async () => {
    mockApi(
      AUTHOR,
      builderRoutes(
        course({
          editable: false,
          status: { key: 'in_review', label: 'In review' },
          actions: { start_draft: false, submit: false, publish: false, return_to_draft: false },
        }),
      ),
    )
    renderAt('/studio/courses/1/curriculum/3')
    await screen.findByRole('navigation', { name: 'Course outline' })
    expect(screen.queryByRole('button', { name: /Add (lesson|module|section)/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Reorder/ })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Lesson title')).toBeDisabled()
    expect(screen.getByText(/locked for editing/)).toBeInTheDocument()
  })

  it('autosaves a renamed lesson on blur', async () => {
    const calls = mockApi(AUTHOR, {
      ...builderRoutes(),
      [`PATCH ${BASE}/nodes/3/`]: () => ({ body: node(3, 'topic', 'Renamed') }),
    })
    renderAt('/studio/courses/1/curriculum/3')
    const title = await screen.findByLabelText('Lesson title')
    fireEvent.change(title, { target: { value: 'Renamed' } })
    fireEvent.blur(title)
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ title: 'Renamed' }),
    )
    expect(await screen.findByText('Saved')).toBeInTheDocument()
  })

  it('flags activities that still need setup', async () => {
    mockApi(AUTHOR, builderRoutes())
    renderAt('/studio/courses/1/curriculum/3')
    expect(await screen.findByText('Needs setup')).toBeInTheDocument()
    expect(screen.getByLabelText(/Link to the reading/)).toBeInTheDocument() // opened by default
  })
})

describe('Schema-driven activity form', () => {
  it('saves the whole config, merged, when a field loses focus', async () => {
    const calls = mockApi(AUTHOR, {
      [`GET ${BASE}/courses/1/`]: () => ({ body: course() }),
      [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
      [`PATCH ${BASE}/activities/9/`]: () => ({ body: {} }),
    })
    renderAt('/studio/courses/1/curriculum/3')
    const field = await screen.findByLabelText(/Link to the reading/)
    fireEvent.change(field, { target: { value: 'https://x.io' } })
    fireEvent.blur(field)
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/activities/9/'))?.body).toEqual({
        config: { source_url: 'https://x.io' },
      }),
    )
  })

  it('saves a pasted link straight away, says so, and does not save it twice on blur', async () => {
    const saved = course()
    const reading = saved.tree!.root!.children[0].children[0].children[0].activities[0]
    const calls = mockApi(AUTHOR, {
      // Like the real server, the course read after the save carries the new link.
      [`GET ${BASE}/courses/1/`]: () => ({ body: calls.some((c) => c.method === 'PATCH') ? saved : course() }),
      [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
      [`PATCH ${BASE}/activities/9/`]: () => {
        reading.config = { source_url: 'https://docs.hevodata.com/sources/' }
        return { body: {} }
      },
    })
    renderAt('/studio/courses/1/curriculum/3')
    const field = await screen.findByLabelText(/Link to the reading/)
    fireEvent.change(field, { target: { value: 'https://docs.hevodata.com/sources/' } })
    fireEvent.paste(field)
    expect(await screen.findByText('Saved')).toBeInTheDocument()
    fireEvent.blur(field)
    const saves = () => calls.filter((c) => c.method === 'PATCH' && c.path.endsWith('/activities/9/'))
    expect(saves()).toHaveLength(1)
    expect(saves()[0].body).toEqual({ config: { source_url: 'https://docs.hevodata.com/sources/' } })
  })

  it('saves a link on Enter', async () => {
    const calls = mockApi(AUTHOR, {
      [`GET ${BASE}/courses/1/`]: () => ({ body: course() }),
      [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
      [`PATCH ${BASE}/activities/9/`]: () => ({ body: {} }),
    })
    renderAt('/studio/courses/1/curriculum/3')
    const field = await screen.findByLabelText(/Link to the reading/)
    fireEvent.change(field, { target: { value: 'https://x.io' } })
    fireEvent.keyDown(field, { key: 'Enter' })
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
  })

  it('keeps both edits when a second field is changed before the first save returns', async () => {
    const calls = mockApi(AUTHOR, {
      [`GET ${BASE}/courses/1/`]: () => ({ body: course() }), // never reflects the saves
      [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
      [`PATCH ${BASE}/activities/9/`]: () => ({ body: {} }),
    })
    renderAt('/studio/courses/1/curriculum/3')
    const link = await screen.findByLabelText(/Link to the reading/)
    const minutes = screen.getByLabelText(/Read time/)
    fireEvent.change(link, { target: { value: 'https://docs.hevodata.com/sources/' } })
    fireEvent.blur(link)
    fireEvent.change(minutes, { target: { value: '8' } })
    fireEvent.blur(minutes)
    await waitFor(() => expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(2))
    const bodies = calls.filter((c) => c.method === 'PATCH').map((c) => c.body)
    expect(bodies[1]).toEqual({
      config: { source_url: 'https://docs.hevodata.com/sources/', estimated_read_minutes: 8 },
    })
  })

  it('shows an inline error for invalid JSON and does not call the server', async () => {
    const c = course()
    c.tree!.root!.children[0].children[0].children[0].activities = [
      {
        id: 10,
        activity_type: 'poll',
        title: 'Poll',
        config: { questions: [] },
        is_required: true,
        points: 0,
        max_attempts: 3,
        mastery_threshold: null,
        order: 0,
        needs_setup: true,
        completable: false,
      },
    ]
    const calls = mockApi(AUTHOR, {
      [`GET ${BASE}/courses/1/`]: () => ({ body: c }),
      [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
    })
    renderAt('/studio/courses/1/curriculum/3')
    const box = await screen.findByLabelText(/Questions/)
    fireEvent.change(box, { target: { value: '[{' } })
    fireEvent.blur(box)
    expect(await screen.findByText('That isn’t valid JSON.')).toBeInTheDocument()
    expect(calls.some((x) => x.method === 'PATCH')).toBe(false)
  })
})

describe('Quiz editor', () => {
  function quizCourse(config: Record<string, unknown> = {}, maxAttempts = 0) {
    const c = course()
    c.tree!.root!.children[0].children[0].children[0].activities = [
      {
        id: 20,
        activity_type: 'mcq',
        title: 'Sources quiz',
        config: {
          questions: [{ text: 'Where from?', choices: ['Source', 'Sink'], answer: 0 }],
          pass_threshold: 0.7,
          ...config,
        },
        is_required: true,
        points: 0,
        max_attempts: maxAttempts,
        mastery_threshold: null,
        order: 0,
        needs_setup: false,
        completable: true,
      },
    ]
    return c
  }

  async function open(c: AuthCourse = quizCourse()) {
    const calls = mockApi(AUTHOR, {
      [`GET ${BASE}/courses/1/`]: () => ({ body: c }),
      [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
      [`PATCH ${BASE}/activities/20/`]: () => ({ body: {} }),
    })
    renderAt('/studio/courses/1/curriculum/3')
    fireEvent.click(await screen.findByRole('button', { name: /Show settings for “Sources quiz”/ }))
    return calls
  }

  const patches = (calls: { method: string; path: string; body: unknown }[]) =>
    calls.filter((c) => c.method === 'PATCH' && c.path.endsWith('/activities/20/')).map((c) => c.body)

  it('replaces the generic form with question, choice and answer fields — no JSON', async () => {
    await open()
    expect(await screen.findByText('Question 1')).toBeInTheDocument()
    expect(screen.getByLabelText('Question 1 text')).toHaveValue('Where from?')
    expect(screen.getByLabelText('Choice 2 of question 1')).toHaveValue('Sink')
    expect(screen.getByLabelText('Choice 1 is correct')).toBeChecked()
    expect(screen.getByLabelText('Pass mark (%)')).toHaveValue(70)
    expect(screen.getByLabelText('Attempts allowed')).toHaveValue(0)
    expect(screen.queryByText('That isn’t valid JSON.')).not.toBeInTheDocument()
  })

  it('saves a changed correct answer into the config', async () => {
    const calls = await open()
    fireEvent.click(await screen.findByLabelText('Choice 2 is correct'))
    await waitFor(() =>
      expect(patches(calls)).toEqual([
        {
          config: {
            questions: [{ text: 'Where from?', choices: ['Source', 'Sink'], answer: 1 }],
            pass_threshold: 0.7,
          },
        },
      ]),
    )
  })

  it('turns a question into "select all that apply" and ticks several', async () => {
    const calls = await open()
    fireEvent.click(await screen.findByLabelText('More than one correct answer'))
    await waitFor(() => expect(patches(calls)).toHaveLength(1))
    expect((patches(calls)[0] as { config: { questions: { answer: unknown }[] } }).config.questions[0].answer).toEqual([0])
  })

  it('adds a question and a choice', async () => {
    const calls = await open()
    fireEvent.click(await screen.findByRole('button', { name: 'Add question' }))
    await waitFor(() => expect(patches(calls)).toHaveLength(1))
    const added = (patches(calls)[0] as { config: { questions: unknown[] } }).config.questions
    expect(added[1]).toEqual({ text: '', choices: ['', ''] })

    fireEvent.click(screen.getByRole('button', { name: 'Add choice' }))
    await waitFor(() => expect(patches(calls)).toHaveLength(2))
    const grown = (patches(calls)[1] as { config: { questions: { choices: string[] }[] } }).config.questions
    expect(grown[0].choices).toEqual(['Source', 'Sink', ''])
  })

  it('saves the question text when you leave the field', async () => {
    const calls = await open()
    const field = await screen.findByLabelText('Question 1 text')
    fireEvent.change(field, { target: { value: 'Where does data start?' } })
    fireEvent.blur(field)
    await waitFor(() => expect(patches(calls)).toHaveLength(1))
    expect((patches(calls)[0] as { config: { questions: { text: string }[] } }).config.questions[0].text).toBe(
      'Where does data start?',
    )
  })

  it('stores the pass mark as a fraction and the attempts as a number', async () => {
    const calls = await open()
    const pass = await screen.findByLabelText('Pass mark (%)')
    fireEvent.change(pass, { target: { value: '80' } })
    fireEvent.blur(pass)
    const attempts = screen.getByLabelText('Attempts allowed')
    fireEvent.change(attempts, { target: { value: '5' } })
    fireEvent.blur(attempts)
    await waitFor(() => expect(patches(calls)).toHaveLength(2))
    expect(patches(calls)).toContainEqual(expect.objectContaining({ config: expect.objectContaining({ pass_threshold: 0.8 }) }))
    expect(patches(calls)).toContainEqual({ max_attempts: 5 })
  })

  it('refuses a pass mark that is not a percentage, without calling the server', async () => {
    const calls = await open()
    const pass = await screen.findByLabelText('Pass mark (%)')
    fireEvent.change(pass, { target: { value: '150' } })
    fireEvent.blur(pass)
    expect(await screen.findByText('Enter a percentage from 0 to 100.')).toBeInTheDocument()
    expect(patches(calls)).toHaveLength(0)
  })

  it('asks before deleting a question that has content', async () => {
    const calls = await open()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete question 1' }))
    expect(await screen.findByRole('alertdialog')).toHaveTextContent('Delete question 1?')
    expect(patches(calls)).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Delete question' }))
    await waitFor(() =>
      expect(patches(calls)).toEqual([{ config: { questions: [], pass_threshold: 0.7 } }]),
    )
  })

  it('keeps every edit made in quick succession, not just the last one', async () => {
    const empty = quizCourse({ questions: [{ text: '', choices: ['', ''] }] })
    const calls = mockApi(AUTHOR, {
      [`GET ${BASE}/courses/1/`]: () => ({ body: empty }), // never reflects the saves
      [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
      [`PATCH ${BASE}/activities/20/`]: () => ({ body: {} }),
    })
    renderAt('/studio/courses/1/curriculum/3')
    fireEvent.click(await screen.findByRole('button', { name: /Show settings for “Sources quiz”/ }))
    const fields = await Promise.all(
      ['Question 1 text', 'Choice 1 of question 1', 'Choice 2 of question 1'].map((label) =>
        screen.findByLabelText(label),
      ),
    )
    // All typed before any save has come back, as a quick typist would.
    fields.forEach((field, i) => {
      fireEvent.change(field, { target: { value: ['Where from?', 'A source', 'A destination'][i] } })
      fireEvent.blur(field)
    })
    fireEvent.click(screen.getByLabelText('Choice 1 is correct'))
    await waitFor(() => expect(patches(calls)).toHaveLength(4))
    expect((patches(calls)[3] as { config: unknown }).config).toMatchObject({
      questions: [{ text: 'Where from?', choices: ['A source', 'A destination'], answer: 0 }],
    })
  })

  it('says so when a button-driven edit is refused, instead of failing silently', async () => {
    const c = quizCourse()
    mockApi(AUTHOR, {
      [`GET ${BASE}/courses/1/`]: () => ({ body: c }),
      [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
      [`PATCH ${BASE}/activities/20/`]: () => ({ status: 400, body: { detail: 'Not allowed right now.' } }),
    })
    renderAt('/studio/courses/1/curriculum/3')
    fireEvent.click(await screen.findByRole('button', { name: /Show settings for “Sources quiz”/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add question' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed right now.')
  })

  it('keeps choices from dropping below two', async () => {
    await open()
    expect(await screen.findByRole('button', { name: 'Remove choice 1 of question 1' })).toBeDisabled()
  })

  it('is read-only when the course is locked', async () => {
    const locked = quizCourse()
    locked.editable = false
    await open(locked)
    expect(await screen.findByLabelText('Question 1 text')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Add question' })).not.toBeInTheDocument()
  })
})

describe('Markdown editor', () => {
  it('inserts a learning pattern and previews it with the learner renderer', async () => {
    mockApi(AUTHOR, {
      [`GET ${BASE}/courses/1/`]: () => ({ body: course() }),
      [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
      [`PATCH ${BASE}/nodes/3/`]: () => ({ body: {} }),
    })
    renderAt('/studio/courses/1/curriculum/3')
    const intro = (await screen.findByLabelText('Introduction')) as HTMLTextAreaElement
    fireEvent.click(screen.getAllByRole('button', { name: 'Insert' })[0])
    fireEvent.click(await screen.findByRole('menuitem', { name: /Key idea/ }))
    await waitFor(() => expect(intro.value).toContain('> [!IDEA]'))

    fireEvent.change(intro, { target: { value: '> [!IDEA]\n> Hold onto this.' } })
    fireEvent.click(screen.getAllByRole('tab', { name: 'Preview' })[0])
    const note = await screen.findByRole('note', { name: 'Key idea' })
    expect(note).toHaveTextContent('Hold onto this.')
  })
})

describe('Publish workflow', () => {
  const routes = (c: AuthCourse, extra: Record<string, Handler> = {}) => ({
    [`GET ${BASE}/courses/1/`]: () => ({ body: c }),
    [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
    ...extra,
  })

  it('a trainer sees Submit for publish, never Publish; issues block it', async () => {
    mockApi(
      AUTHOR,
      routes(course(), {
        [`GET ${BASE}/courses/1/publish-checklist/`]: () => ({
          body: {
            ok: false,
            issues: [{ message: '“Reading” needs setup.', node_id: 4, level: 'error' }],
          },
        }),
      }),
    )
    renderAt('/studio/courses/1/curriculum')
    expect(screen.queryByRole('button', { name: 'Publish' })).not.toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Submit for publish' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByRole('link', { name: /needs setup/ })).toHaveAttribute(
      'href',
      '/studio/courses/1/curriculum/4',
    )
    expect(within(dialog).getByRole('button', { name: 'Submit' })).toBeDisabled()
  })

  it('submits when the checklist is clean and shows the review state', async () => {
    const inReview = course({
      status: { key: 'in_review', label: 'In review' },
      editable: false,
      actions: { start_draft: false, submit: false, publish: false, return_to_draft: false },
    })
    const calls = mockApi(
      AUTHOR,
      routes(course(), {
        [`GET ${BASE}/courses/1/publish-checklist/`]: () => ({ body: { ok: true, issues: [] } }),
        [`POST ${BASE}/courses/1/submit/`]: () => ({ body: inReview }),
      }),
    )
    renderAt('/studio/courses/1/curriculum')
    fireEvent.click(await screen.findByRole('button', { name: 'Submit for publish' }))
    const dialog = await screen.findByRole('dialog')
    const confirm = await within(dialog).findByRole('button', { name: 'Submit' })
    await waitFor(() => expect(confirm).toBeEnabled())
    fireEvent.click(confirm)

    expect(await screen.findByText('Waiting for an administrator to publish.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.path.endsWith('/submit/'))).toBe(true)
  })

  it('a publisher can publish a submitted course or send it back', async () => {
    const inReview = course({
      status: { key: 'in_review', label: 'In review' },
      editable: false,
      actions: { start_draft: false, submit: false, publish: true, return_to_draft: true },
    })
    mockApi(PUBLISHER, routes(inReview))
    renderAt('/studio/courses/1/curriculum')
    expect(await screen.findByRole('button', { name: 'Publish' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Return to draft' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Submit for publish' })).not.toBeInTheDocument()
  })

  it('a published course offers Edit, which starts a draft and opens the builder', async () => {
    const published = course({
      status: { key: 'published', label: 'Published v1' },
      editable: false,
      actions: { start_draft: true, submit: false, publish: false, return_to_draft: false },
    })
    const calls = mockApi(
      AUTHOR,
      routes(published, {
        [`POST ${BASE}/courses/1/draft/`]: () => ({
          status: 201,
          body: course({ status: { key: 'published_with_draft', label: 'Published v1 · edits in draft' } }),
        }),
      }),
    )
    renderAt('/studio/courses/1/curriculum')
    fireEvent.click(await screen.findByRole('button', { name: 'Edit course' }))
    expect(await screen.findByText('Published v1 · edits in draft')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.path.endsWith('/draft/'))).toBe(true)
  })

  it('a unified Escape closes the dialog and returns focus', async () => {
    mockApi(
      AUTHOR,
      routes(course(), {
        [`GET ${BASE}/courses/1/publish-checklist/`]: () => ({ body: { ok: true, issues: [] } }),
      }),
    )
    renderAt('/studio/courses/1/curriculum')
    const opener = await screen.findByRole('button', { name: 'Submit for publish' })
    opener.focus()
    fireEvent.click(opener)
    await screen.findByRole('dialog')
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(opener).toHaveFocus()
  })
})

describe('Import wizard', () => {
  const preview = (over = {}) => ({
    headers: ['Module', 'Lesson'],
    mapping: { module: 'Module', lesson: 'Lesson', section: null },
    counts: { modules: 1, lessons: 2, sections: 0, activities: 0 },
    outline: [
      {
        title: 'Foundations',
        level: 'module',
        activities: [],
        children: [{ title: 'Pipelines', level: 'lesson', activities: [], children: [] }],
      },
    ],
    errors: [],
    warnings: [],
    ok: true,
    ...over,
  })

  function pick() {
    const file = new File(['Module,Lesson\nM,L\n'], 'plan.csv', { type: 'text/csv' })
    fireEvent.change(document.getElementById('import-file')!, { target: { files: [file] } })
  }

  const base = {
    [`GET ${BASE}/courses/1/`]: () => ({ body: course() }),
    [`GET ${BASE}/activity-types/`]: () => ({ body: TYPES }),
  }

  it('previews counts and the tree, then commits', async () => {
    const calls = mockApi(AUTHOR, {
      ...base,
      [`POST ${BASE}/courses/1/import/preview/`]: () => ({ body: preview() }),
      [`POST ${BASE}/courses/1/import/commit/`]: () => ({
        status: 201,
        body: { counts: preview().counts, course: course() },
      }),
    })
    renderAt('/studio/courses/1/import')
    await screen.findByText('1. Choose a spreadsheet')
    pick()

    expect(await screen.findByText(/1 module · 2 lessons/)).toBeInTheDocument()
    expect(screen.getByText('Foundations')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Import into this course' }))
    expect(await screen.findByText('Imported.')).toBeInTheDocument()
    expect(calls.some((c) => c.path.endsWith('/import/commit/'))).toBe(true)
  })

  it('lists row-numbered problems and blocks the import', async () => {
    mockApi(AUTHOR, {
      ...base,
      [`POST ${BASE}/courses/1/import/preview/`]: () => ({
        body: preview({
          ok: false,
          errors: [{ row: 4, message: 'Unknown activity type “hologram”.' }],
        }),
      }),
    })
    renderAt('/studio/courses/1/import')
    await screen.findByText('1. Choose a spreadsheet')
    pick()
    expect(await screen.findByText('Row 4')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import into this course' })).toBeDisabled()
  })

  it('explains that import needs an editable draft', async () => {
    mockApi(
      AUTHOR,
      {
        ...base,
        [`GET ${BASE}/courses/1/`]: () => ({ body: course({ editable: false }) }),
      },
    )
    renderAt('/studio/courses/1/import')
    expect(await screen.findByText(/Start editing the course first/)).toBeInTheDocument()
  })
})

describe('Preview as learner', () => {
  it('mounts the learner screens on the draft, with links that stay in preview', async () => {
    mockApi(AUTHOR, {
      [`GET ${BASE}/courses/1/preview/`]: () => ({
        body: { id: 1, course_id: 1, version: 1, published_at: null, root: sampleCourse },
      }),
    })
    renderAt('/studio/courses/1/preview')
    expect(await screen.findByText(/Previewing the draft/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Back to the builder/ })).toHaveAttribute(
      'href',
      '/studio/courses/1/curriculum',
    )
    expect(screen.getByRole('link', { name: /start course/i })).toHaveAttribute(
      'href',
      '/studio/courses/1/preview/lessons/3',
    )
  })

  it('keeps the banner and the preview prefix on a lesson page', async () => {
    mockApi(AUTHOR, {
      [`GET ${BASE}/courses/1/preview/`]: () => ({
        body: { id: 1, course_id: 1, version: 1, published_at: null, root: sampleCourse },
      }),
    })
    renderAt('/studio/courses/1/preview/lessons/3')
    expect(await screen.findByRole('heading', { level: 1, name: 'Pipelines' })).toBeInTheDocument()
    expect(screen.getByText(/Previewing the draft/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Up next.*Failures/ })).toHaveAttribute(
      'href',
      '/studio/courses/1/preview/lessons/7',
    )
  })
})
