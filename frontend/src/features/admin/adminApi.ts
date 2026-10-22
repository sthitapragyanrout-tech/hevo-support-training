import { request } from '../../lib/api'

export interface Paged<T> {
  results: T[]
  count: number
  page: number
  pages: number
  page_size: number
}

export interface Query {
  [key: string]: string | number | undefined
}

/** `?a=1&b=2` from the set values only. */
export function queryString(query: Query): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

const admin = (path: string, query: Query = {}) => `/api/v1/admin/${path}${queryString(query)}`

// ----------------------------------------------------------------- results

export interface CourseOption {
  id: number
  title: string
}

export interface LearnerRow {
  id: number
  name: string
  email: string
  employee_id: string | null
  lessons_completed: number
  quiz_attempts: number
  last_activity: string | null
}

export interface AttemptRow {
  number: number
  score: number
  correct: number
  total: number
  passed: boolean
  submitted_at: string
}

export type ActivityStatus = 'not_started' | 'started' | 'completed' | 'exhausted'

export interface LearnerActivity {
  id: number
  title: string
  type: string
  lesson: string
  required: boolean
  state: ActivityStatus
  scored: boolean
  best_score: number | null
  attempts: AttemptRow[]
  max_attempts: number
}

export interface LearnerCourse {
  course_id: number
  title: string
  version: number
  state: string
  lessons_total: number
  lessons_completed: number
  activities: LearnerActivity[]
}

export interface LearnerDetail {
  id: number
  name: string
  email: string
  employee_id: string | null
  courses: LearnerCourse[]
}

export interface QuizRow {
  id: number
  title: string
  course: string
  course_id: number
  version: number
  lesson: string
  required: boolean
  learners: number
  passed: number
  not_passed: number
  in_progress: number
  average_best_score: number | null
}

export interface QuizLearnerRow {
  user_id: number
  name: string
  email: string
  state: ActivityStatus
  attempts: number
  best_score: number | null
  last_score: number | null
  last_attempt_at: string | null
}

export interface QuizDetail {
  id: number
  title: string
  course: string
  version: number
  lesson: string
  max_attempts: number
  learners: QuizLearnerRow[]
}

export interface AuditEntry {
  id: number
  created_at: string
  actor: string
  action: string
  target_type: string
  target_id: string
  target: string
  changes: Record<string, unknown>
  ip_address: string | null
}

// ------------------------------------------------------------- users & roles

export interface UserRow {
  id: number
  name: string
  email: string
  username: string
  employee_id: string | null
  is_active: boolean
  roles: string[]
  last_login: string | null
  locked: boolean
  must_change_password: boolean
}

export interface UserDetail extends UserRow {
  first_name: string
  last_name: string
  timezone: string
  date_joined: string
  is_staff: boolean
  is_superuser: boolean
  /** Only a superuser may change staff/superuser access. */
  can_edit_privileges: boolean
  is_self: boolean
  identities: { provider: string; external_id: string; email: string }[]
  /** Present only on creation, and only when the server generated one. */
  temporary_password?: string
}

export interface UserChanges {
  first_name?: string
  last_name?: string
  email?: string
  employee_id?: string | null
  timezone?: string
  must_change_password?: boolean
  is_active?: boolean
  is_staff?: boolean
  is_superuser?: boolean
}

export interface NewUser {
  email: string
  first_name?: string
  last_name?: string
  employee_id?: string
  password?: string
  roles?: string[]
}

export interface RoleOption {
  name: string
  label: string
  builtin: boolean
}

export interface RoleRow {
  id: number
  name: string
  label: string
  /** Built-in roles can't be renamed or deleted. */
  builtin: boolean
  permissions: string[]
  members: number
  /** Actions this role can never lose (so an Admin can always undo a mistake). */
  locked: string[]
}

export interface ActionInfo {
  key: string
  label: string
  description: string
}

// ------------------------------------------------------------------ courses

export interface CourseRow {
  id: number
  title: string
  slug: string
  status: { key: string; label: string }
  created_by: string | null
  created_at: string
  archived_at: string | null
  versions: number
  published_version: number | null
}

export interface VersionRow {
  id: number
  number: number
  state: string
  state_label: string
  title: string | null
  lessons: number
  activities: number
  learners: number
  submitted_at: string | null
  submitted_by: string | null
  published_at: string | null
  published_by: string | null
}

export interface CourseDetail extends CourseRow {
  versions_history: VersionRow[]
  can_archive: boolean
}

// ----------------------------------------------------------------- sign-ins

export interface SignInRow {
  id: number
  when: string
  username: string
  user_id: number | null
  name: string | null
  ip_address: string | null
  user_agent: string
  /** Successful sign-ins only. */
  signed_out_at?: string | null
  /** Failed attempts only. */
  locked_out?: boolean
}

const json = (body: unknown) => JSON.stringify(body)

export const adminApi = {
  courses: () => request<{ results: CourseOption[] }>(admin('results/courses/')),
  learners: (q: Query) => request<Paged<LearnerRow>>(admin('results/learners/', q)),
  learner: (id: number | string) => request<LearnerDetail>(admin(`results/learners/${id}/`)),
  resetAttempts: (learnerId: number, activityId: number) =>
    request<void>(admin(`results/learners/${learnerId}/activities/${activityId}/attempts/`), {
      method: 'DELETE',
    }),
  quizzes: (q: Query) => request<Paged<QuizRow>>(admin('results/quizzes/', q)),
  quiz: (id: number | string) => request<QuizDetail>(admin(`results/quizzes/${id}/`)),
  /** A plain link: the browser downloads the CSV with the session cookie. */
  exportUrl: (course?: number | string) => admin('results/export/', { course }),
  courseList: (q: Query) => request<Paged<CourseRow>>(admin('courses/', q)),
  course: (id: number | string) => request<CourseDetail>(admin(`courses/${id}/`)),
  archiveCourse: (id: number) =>
    request<CourseRow>(admin(`courses/${id}/archive/`), { method: 'POST' }),
  restoreCourse: (id: number) =>
    request<CourseRow>(admin(`courses/${id}/restore/`), { method: 'POST' }),
  signIns: (q: Query) => request<Paged<SignInRow> & { kind: string }>(admin('signins/', q)),
  users: (q: Query) => request<Paged<UserRow>>(admin('users/', q)),
  user: (id: number | string) => request<UserDetail>(admin(`users/${id}/`)),
  createUser: (body: NewUser) =>
    request<UserDetail>(admin('users/'), { method: 'POST', body: json(body) }),
  updateUser: (id: number, body: UserChanges) =>
    request<UserDetail>(admin(`users/${id}/`), { method: 'PATCH', body: json(body) }),
  setPassword: (id: number, password = '') =>
    request<{ temporary_password?: string; ok?: boolean }>(admin(`users/${id}/set-password/`), {
      method: 'POST',
      body: json({ password }),
    }),
  unlock: (id: number) =>
    request<{ cleared: number }>(admin(`users/${id}/unlock/`), { method: 'POST' }),
  setUserRoles: (id: number, roles: string[]) =>
    request<{ roles: string[] }>(admin(`users/${id}/roles/`), { method: 'PUT', body: json({ roles }) }),
  roles: () => request<{ roles: RoleRow[]; actions: ActionInfo[] }>(admin('roles/')),
  roleOptions: () => request<{ results: RoleOption[] }>(admin('roles/options/')),
  createRole: (name: string, permissions: string[] = []) =>
    request<RoleRow>(admin('roles/new/'), { method: 'POST', body: json({ name, permissions }) }),
  renameRole: (id: number, name: string) =>
    request<RoleRow>(admin(`roles/${id}/`), { method: 'PATCH', body: json({ name }) }),
  deleteRole: (id: number) => request<void>(admin(`roles/${id}/`), { method: 'DELETE' }),
  setRolePermissions: (id: number, permissions: string[]) =>
    request<RoleRow>(admin(`roles/${id}/permissions/`), {
      method: 'PUT',
      body: json({ permissions }),
    }),
  audit: (q: Query) => request<Paged<AuditEntry>>(admin('audit/', q)),
  auditActions: () => request<{ results: string[] }>(admin('audit/actions/')),
}
