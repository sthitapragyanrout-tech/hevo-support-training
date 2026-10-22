import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import App from '../../App'
import { AuthProvider } from '../../lib/auth'

export interface Call {
  method: string
  path: string
  query: URLSearchParams
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
const DEFAULTS: Record<string, unknown> = { 'GET /api/v1/admin/roles/options/': ROLE_OPTIONS }

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
      const call = { method, path, query: new URLSearchParams(search) }
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
