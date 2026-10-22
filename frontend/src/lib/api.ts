export interface User {
  id: number
  username: string
  email: string
  employee_id: string | null
  must_change_password: boolean
  /** True only when the server is enforcing a change *and* this account owes one. */
  password_change_required?: boolean
  /** Break-glass access to Django Admin; shown only to superusers. */
  is_superuser?: boolean
  roles: string[]
  /** Actions the server says this user may perform (from `can()`), e.g.
   * "catalog.author_content". Drives which UI is shown; the server still enforces. */
  capabilities: string[]
}

interface SessionResponse {
  authenticated: boolean
  user: User | null
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return match ? decodeURIComponent(match[1]) : null
}

/** DRF returns `{detail}` for most errors and `{field: [messages]}` for
 * validation errors; show whichever human sentence is there. */
function describeError(body: unknown, fallback: string): string {
  if (body && typeof body === 'object') {
    const record = body as Record<string, unknown>
    if (typeof record.detail === 'string') return record.detail
    for (const [field, value] of Object.entries(record)) {
      const message = Array.isArray(value) ? value[0] : value
      if (typeof message === 'string') return field === 'non_field_errors' ? message : `${field}: ${message}`
    }
  }
  return fallback
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase()
  const headers = new Headers(options.headers)
  // A FormData body sets its own multipart boundary header.
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')

  // Django's CSRF middleware requires this on every unsafe-method request
  // once a csrftoken cookie exists (set by GET /session/ on app load).
  if (method !== 'GET' && method !== 'HEAD') {
    const csrfToken = getCookie('csrftoken')
    if (csrfToken) headers.set('X-CSRFToken', csrfToken)
  }

  const response = await fetch(path, {
    ...options,
    method,
    headers,
    credentials: 'same-origin',
  })

  if (!response.ok) {
    let detail = response.statusText
    try {
      detail = describeError(await response.json(), detail)
    } catch {
      // no JSON body — fall back to statusText
    }
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export type NodeKind = 'course' | 'segment' | 'topic' | 'subtopic'

export interface ActivitySummary {
  id: number
  activity_type: string
  title: string
  is_required: boolean
  points: number
  order: number
  /** Tries allowed for scored activities; 0 means unlimited. */
  max_attempts: number
  /** Only the keys a learner may see (a reading's link, never a quiz key). */
  config: Record<string, unknown>
  /** Can the learner finish this kind of activity today? */
  completable: boolean
}

export interface TreeNode {
  id: number
  kind: NodeKind
  title: string
  slug: string
  description: string
  is_required: boolean
  estimated_minutes: number | null
  activities: ActivitySummary[]
  children: TreeNode[]
}

export interface CourseSummary {
  id: number
  course_id: number
  title: string
  description: string
  version: number
  published_at: string | null
}

export interface CourseTree {
  id: number
  course_id: number
  version: number
  published_at: string | null
  root: TreeNode | null
}

export const catalogApi = {
  courses: () => request<CourseSummary[]>('/api/v1/catalog/courses/'),
  course: (id: number | string) => request<CourseTree>(`/api/v1/catalog/courses/${id}/`),
}

export const authApi = {
  session: () => request<SessionResponse>('/api/v1/auth/session/'),
  login: (login: string, password: string) =>
    request<{ user: User }>('/api/v1/auth/login/', {
      method: 'POST',
      body: JSON.stringify({ login, password }),
    }),
  logout: () => request<void>('/api/v1/auth/logout/', { method: 'POST' }),
  changePassword: (current_password: string, new_password: string) =>
    request<{ user: User }>('/api/v1/auth/password/', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),
}

/** `exhausted`: a scored activity whose attempts are all used without a pass. */
export type ActivityState = 'started' | 'completed' | 'exhausted'

/** What the learner has done on a scored activity so far. */
export interface AttemptSummary {
  count: number
  best_score: number
  last_score: number
  /** Null when attempts are unlimited. */
  attempts_left: number | null
}

export interface CourseProgressPayload {
  completed_lessons: number[]
  activities: Record<string, ActivityState>
  attempts: Record<string, AttemptSummary>
  /** Whether this server lets a learner wipe their own quiz attempts (testing). */
  can_reset_attempts: boolean
}

/** Per-question feedback. The key and explanation arrive only once the quiz
 * is passed or the last attempt is spent. */
export interface QuestionReview {
  correct: boolean
  correct_answers?: number[]
  explanation?: string
}

export interface AttemptResult {
  state: ActivityState
  passed: boolean
  score: number
  correct: number
  total: number
  /** Questions that had to be right to pass (unknown when reloading an old try). */
  needed: number | null
  attempts_left: number | null
  /** What the learner picked, one list of choice indexes per question. */
  picks: number[][]
  review: QuestionReview[]
  history: AttemptHistoryRow[]
}

/** One try, as listed under "Your attempts". */
export interface AttemptHistoryRow {
  number: number
  score: number
  correct: number
  total: number
  passed: boolean
  submitted_at: string
}

export interface AttemptReport {
  history: AttemptHistoryRow[]
  latest: AttemptResult | null
}

const progress = (path: string) => `/api/v1/progress/${path}`

export const progressApi = {
  course: (versionId: number | string) =>
    request<CourseProgressPayload>(progress(`courses/${versionId}/`)),
  startActivity: (id: number) =>
    request<{ state: ActivityState }>(progress(`activities/${id}/start/`), { method: 'POST' }),
  completeActivity: (id: number) =>
    request<{ state: ActivityState }>(progress(`activities/${id}/complete/`), { method: 'POST' }),
  uncompleteActivity: (id: number) =>
    request<{ state: ActivityState | null }>(progress(`activities/${id}/complete/`), {
      method: 'DELETE',
    }),
  submitAttempt: (id: number, answers: number[][]) =>
    request<AttemptResult>(progress(`activities/${id}/attempts/`), {
      method: 'POST',
      body: JSON.stringify({ answers }),
    }),
  attempts: (id: number) => request<AttemptReport>(progress(`activities/${id}/attempts/`)),
  resetAttempts: (id: number) =>
    request<void>(progress(`activities/${id}/attempts/`), { method: 'DELETE' }),
  completeLesson: (id: number) =>
    request<{ completed: boolean }>(progress(`lessons/${id}/complete/`), { method: 'POST' }),
  uncompleteLesson: (id: number) =>
    request<void>(progress(`lessons/${id}/complete/`), { method: 'DELETE' }),
}
