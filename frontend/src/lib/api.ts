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

export function getCookie(name: string): string | null {
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
  learning_order?: 'free' | 'sequential'
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
  /** Lessons the learner has moved past on the strength of work handed in for a mentor's
   * rating: open for what follows, but not complete until it passes. */
  awaiting_review_lessons?: number[]
  activities: Record<string, ActivityState>
  attempts: Record<string, AttemptSummary>
  /** Whether this server lets a learner wipe their own quiz attempts (testing). */
  can_reset_attempts: boolean
  /** `sequential`: lessons unlock in order. `free`: everything is open. */
  learning_order?: 'free' | 'sequential'
  /** Locked lessons only: what to finish first. */
  locked?: Record<string, { blocked_by: number; blocked_by_title: string }>
  /** The first open, unfinished lesson (required ones first). */
  next_lesson_id?: number | null
  /** Videos the learner has started: how much of each they've verifiably watched. */
  watch?: Record<string, WatchSummary>
  /** Practice tickets the learner has opened: the one in progress and the last finished. */
  sim?: Record<string, SimSummary>
  /** Mentor-rated simulations the learner has opened: where their work stands. */
  rated?: Record<string, RatedSummary>
}

export type RatedStatus =
  | 'not_opened'
  | 'not_submitted'
  | 'waiting'
  | 'changes_requested'
  | 'passed'
  | 'waived'
  | 'not_passed'

export interface RatedSummary {
  status: RatedStatus
  revisions: number
  due_at: string | null
  overdue: boolean
  /** The latest rating, out of 5 (never a percentage). */
  last_score: number | null
  /** What the next lesson waits for: handing the work in, or a passing rating. */
  holds_next: 'submit' | 'pass'
}

export interface SimSummary {
  live: { id: number; state: 'open' | 'finishing' } | null
  last_finished: number | null
  /** Questions the learner has passed on. */
  skips_used: number
  /** Their average over finished tickets, scaled 0–1 (×5 for "out of 5"). */
  average: number | null
}

export interface WatchSummary {
  watched_fraction: number
  position: number
}

/** One heartbeat from the player: what it played since the last one. The
 * server decides what counts and whether the video is finished. */
export interface WatchBody {
  session_id: string
  seq: number
  /** Stretches of the video played at a credited speed, in seconds, sorted and disjoint. */
  ranges: [number, number][]
  position: number
  rate: number
  hidden_seconds: number
  /** Only for embedded players, whose length the server can't know. */
  duration?: number
}

export interface WatchReply {
  state: ActivityState | null
  completed: boolean
  watched_fraction: number
  needed_fraction: number
  position: number
  duration: number | null
  accepted_seconds: number
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
  watchState: (id: number) => request<WatchReply>(progress(`activities/${id}/watch/`)),
  /** `keepalive` lets the last heartbeat survive the page closing. */
  watch: (id: number, body: WatchBody, keepalive = false) =>
    request<WatchReply>(progress(`activities/${id}/watch/`), {
      method: 'POST',
      body: JSON.stringify(body),
      keepalive,
    }),
  completeLesson: (id: number) =>
    request<{ completed: boolean }>(progress(`lessons/${id}/complete/`), { method: 'POST' }),
  uncompleteLesson: (id: number) =>
    request<void>(progress(`lessons/${id}/complete/`), { method: 'DELETE' }),
}


// ------------------------------------------------------------ practice tickets

export interface SimThreadItem {
  seq: number
  role: 'customer' | 'intern'
  text: string
  at: string
  kind: 'message' | 'nudge' | 'close'
  /** Replies only: `sending` until the customer has answered. */
  status?: 'sending' | 'sent' | 'failed'
  error?: string
}

export interface SimMetric {
  key: string
  label: string
  raw: number
  max: number
  feedback: string
  /** What the number rests on: only some metrics are checked, others are an AI's opinion. */
  basis: 'model_judgment' | 'deterministic' | 'link_check' | 'link_check+model_relevance' | 'grounded'
}

export interface SimResult {
  score: { raw: number; max: number; scaled: number }
  pass_mark: { raw: number; scaled: number }
  passed: boolean
  metrics: SimMetric[]
  narrative: { strengths: string; weaknesses: string; overall: string } | null
  grounded: boolean
  exchanges: number
  avg_tat_seconds: number
  attempts_left?: number | null
  attempt?: number
  preview?: boolean
  /** `completed` once the quota is met. */
  state?: string
  /** How many scored tickets are done, out of how many are needed to complete. */
  quota?: { done: number; required: number }
}

/** What a trainer's transcript adds. The server never sends these to a learner. */
export interface TrainerSimResult extends SimResult {
  needs_review?: boolean
  review_reasons?: string[]
  scenario_ref?: { topic: string; persona_type: string; issue_summary: string }
}

export interface SimSession {
  id: number
  activity_id: number
  state: 'open' | 'finishing' | 'finished' | 'abandoned'
  preview: boolean
  subject: string
  thread: SimThreadItem[]
  can_reply: boolean
  waiting_for_customer: boolean
  failed: boolean
  failed_message: string
  exchanges: number
  max_exchanges: number
  started_at: string
  customer_waiting_since: string | null
  feedback_pending: boolean
  abandoned_reason: string
  result: SimResult | null
}

const sim = (path: string) => `/api/v1/sim/${path}`
const post = (body?: unknown): RequestInit => ({
  method: 'POST',
  body: body === undefined ? undefined : JSON.stringify(body),
})

export type SkipReason = 'duplicate' | 'unclear' | 'not_relevant'

export const simApi = {
  start: (activityId: number) => request<SimSession>(sim(`activities/${activityId}/sessions/`), post()),
  preview: (activityId: number) => request<SimSession>(sim(`activities/${activityId}/preview/`), post()),
  get: (id: number) => request<SimSession>(sim(`sessions/${id}/`)),
  send: (id: number, text: string, clientId: string) =>
    request<SimSession>(sim(`sessions/${id}/messages/`), post({ text, client_id: clientId })),
  retry: (id: number) => request<SimSession>(sim(`sessions/${id}/retry/`), post()),
  finish: (id: number) => request<SimSession>(sim(`sessions/${id}/finish/`), post()),
  skip: (id: number, reason: SkipReason) =>
    request<SimSession>(sim(`sessions/${id}/skip/`), post({ reason })),
  scenarioCount: (persona: string, topics: string[]) =>
    request<{ count: number }>(
      sim(`scenario-count/?persona=${encodeURIComponent(persona)}&topics=${encodeURIComponent(topics.join(','))}`),
    ),
}


// ----------------------------------------------------------- mentor-rated simulations

export interface RatedFile {
  id: string
  name: string
  type: string
  size_bytes: number
  url: string
  inline: boolean
}

export interface RatedScore {
  key: string
  label: string
  score: number
  max: number
  feedback: string
}

export interface RatedRating {
  raw_score: number
  passed: boolean
  comment: string
  rated_at: string | null
  mentor: string | null
  scores: RatedScore[]
}

export interface RatedRevision {
  id: number
  revision: number
  state: 'submitted' | 'rated' | 'withdrawn'
  submitted_at: string
  late: boolean
  answer: string
  links: string[]
  files: RatedFile[]
  /** When a mentor is expected to have reviewed it (only while it waits). */
  expected_by: string | null
  rating: RatedRating | null
}

export interface RatedCriterion {
  key: string
  label: string
  description: string
}

export interface RatedView {
  activity: { id: number; title: string }
  config: {
    scenario: string
    handin: string
    criteria: RatedCriterion[]
    pass_rule: string
    min_each: number
    allow_files: boolean
    due_days: number
    revision_days: number
    review_hours: number
  }
  limits: {
    max_files: number
    max_file_mb: number
    max_total_mb: number
    types: string[]
    allowed: boolean
    max_answer_chars: number
    max_links: number
  }
  case: {
    status: RatedStatus
    due_at: string | null
    due_basis: 'initial' | 'revision' | 'extended' | null
    overdue: boolean
    revisions: number
    can_submit: boolean
    can_withdraw: boolean
    closed_at: string | null
  }
  revisions: RatedRevision[]
}

const rated = (path: string) => `/api/v1/rated-sims/${path}`

export const ratedApi = {
  get: (activityId: number) => request<RatedView>(rated(`activities/${activityId}/`)),
  open: (activityId: number) => request<RatedView>(rated(`activities/${activityId}/open/`), post()),
  /** Multipart: the answer, links and files go in one request, so nothing is half-saved. */
  submit: (activityId: number, form: FormData) =>
    request<RatedView>(rated(`activities/${activityId}/submissions/`), {
      method: 'POST',
      body: form,
    }),
  withdraw: (submissionId: number) =>
    request<RatedView>(rated(`submissions/${submissionId}/withdraw/`), post()),
}
