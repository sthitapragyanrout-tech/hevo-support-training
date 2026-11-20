import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import App from '../../App'
import { AuthProvider } from '../../lib/auth'

export interface Call {
  method: string
  path: string
  query: URLSearchParams
  /** The JSON the app sent, if any. */
  body: Record<string, unknown> | null
}

export type Reply = { status?: number; body?: unknown }
export type Handler = (call: Call) => Reply

export function user(capabilities: string[], extra: object = {}) {
  return {
    id: 1,
    username: 'u',
    email: 'u@example.com',
    employee_id: null,
    must_change_password: false,
    roles: [],
    capabilities,
    ...extra,
  }
}

/** Routes every screen quietly relies on, so a test only names what it cares about. */
export const ROLE_OPTIONS = {
  results: [
    { name: 'learner', label: 'Learner', builtin: true },
    { name: 'trainer', label: 'Trainer', builtin: true },
    { name: 'mentor', label: 'Mentor', builtin: true },
    { name: 'admin', label: 'Admin', builtin: true },
  ],
}
const DEFAULTS: Record<string, unknown> = {
  'GET /api/v1/admin/roles/options/': ROLE_OPTIONS,
  // The header bell polls this on every page that renders the shell.
  'GET /api/v1/notifications/unread-count/': { unread_count: 0 },
}

export function mockApi(
  capabilities: string[],
  routes: Record<string, Handler | Reply | object | unknown[]>,
  userExtra: object = {},
) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const [path, search = ''] = url.split('?')
      const method = (init.method ?? 'GET').toUpperCase()
      const body = init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
      const call = { method, path, query: new URLSearchParams(search), body }
      calls.push(call)
      let result: Reply = { status: 404, body: { detail: 'Not found.' } }
      if (path.includes('/auth/session/')) {
        result = { body: { authenticated: true, user: user(capabilities, userExtra) } }
      } else {
        const route = routes[`${method} ${path}`] ?? DEFAULTS[`${method} ${path}`]
        if (typeof route === 'function') result = route(call)
        else if (route && typeof route === 'object' && ('body' in route || 'status' in route))
          result = route as Reply
        else if (route !== undefined) result = { body: route }
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

export function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}


export const page = <T,>(results: T[], extra: object = {}) => ({
  results,
  count: results.length,
  page: 1,
  pages: 1,
  page_size: 25,
  ...extra,
})

/** A minimal "enrolled now" course for learner-detail mocks, matching a `courses` entry by
 * version id so its activities show as the current course. */
export function enrolledCourse(courseId: number, versionId: number, title: string) {
  return {
    course_id: courseId,
    version_id: versionId,
    enrollment_id: 100 + courseId,
    version: 1,
    title,
    group: null,
    lessons_total: 3,
    lessons_done: 1,
    lessons_awaiting_review: 0,
    required_lessons_left: 2,
    next_lesson: null,
    quiz_score: null,
    modules: [],
    quizzes: [],
    practice: [],
    rated: [],
    certification: { enabled: false, certificate: null },
  }
}
