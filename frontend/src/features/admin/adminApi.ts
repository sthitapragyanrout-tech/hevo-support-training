import { request, type ProgressCourse, type TrainerSimResult } from '../../lib/api'

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
  lesson_id: number
  required: boolean
  state: ActivityStatus
  scored: boolean
  /** A quiz attempt whose written answers are waiting to be marked. */
  awaiting_review?: boolean
  best_score: number | null
  attempts: AttemptRow[]
  max_attempts: number
  /** Mentor-rated simulations only: where the learner's work stands, for a trainer. */
  rated?: RatedOverview | null
  /** Practice tickets only: each go, with its score, so a trainer can open the transcript. */
  sim?: {
    best_raw: number | null
    /** Finished, scored tickets; the average of their scores; questions skipped; and how many to finish. */
    finished: number
    average_raw: number | null
    skips: number
    required: number
    sessions: {
      id: number
      state: 'open' | 'finishing' | 'finished' | 'abandoned'
      started_at: string
      raw: number | null
      passed: boolean | null
      needs_review: boolean
      reasons: string[]
      repeated: boolean
      abandon_reason: string
      skip_reason: string
    }[]
  } | null
  /** Videos only: how much was verifiably watched, and anything worth a look. */
  watch?: {
    /** Null for a video that can't be measured (Google Drive): the learner confirmed it. */
    watched_fraction: number | null
    needs_review: boolean
    /** Plain-language reasons (never technical codes). */
    reasons: string[]
    fidelity: 'verified' | 'best_effort' | 'self_reported' | null
  } | null
}

export interface LearnerCourse {
  course_id: number
  version_id: number
  title: string
  version: number
  state: string
  lessons_total: number
  lessons_completed: number
  activities: LearnerActivity[]
}

export interface CertificateInfo {
  id: number
  code: string
  issued_at: string
  /** 0–1; null when the course had no scored work (finishing it earned the certificate). */
  score: number | null
}

export interface CertificationPart {
  average: number | null
  scored: number
  items: number
  weight: number
}

export type CertificationStanding =
  | { enabled: false; certificate: CertificateInfo | null }
  | {
      enabled: true
      threshold: number
      score: number | null
      missing: ('quiz' | 'practice' | 'rated')[]
      parts?: Record<'quiz' | 'practice' | 'rated', CertificationPart>
      eligible: boolean
      certificate: CertificateInfo | null
    }

/** One course a learner is on now, at the version they are pinned to (staff copy). */
export interface EnrolledCourse extends Omit<ProgressCourse, 'rated' | 'certification'> {
  enrollment_id: number
  version: number
  group: { id: number; name: string } | null
  quiz_score: number | null
  required_lessons_left: number
  rated: (ProgressCourse['rated'][number] & { last_score: number | null })[]
  certification: CertificationStanding
}

export interface LearnerDetail {
  id: number
  name: string
  email: string
  employee_id: string | null
  /** Every version they have touched, with each activity in detail. */
  courses: LearnerCourse[]
  /** The courses they are enrolled on now. */
  enrolled: EnrolledCourse[]
  /** Every certificate they have held, revoked ones included. */
  certificates: CertificatePage[]
}

export interface DashboardRow {
  enrollment_id: number
  user_id: number
  name: string
  email: string
  employee_id: string | null
  course: { id: number; title: string }
  group: { id: number; name: string } | null
  lessons_done: number
  lessons_total: number
  progress: number
  quiz_score: number | null
  course_score: number | null
  certificate_on: boolean
  threshold: number | null
  certificate: CertificateInfo | null
  last_activity: string | null
}

export interface DashboardPage extends Paged<DashboardRow> {
  totals: { learners: number; enrollments: number; certificates: number; courses: number }
  groups: { id: number; name: string }[]
}

export interface CertificatePage {
  code: string
  name: string
  employee_id: string | null
  course_title: string
  course_id: number
  issued_at: string
  score: number | null
  threshold: number
  revoked: boolean
  id?: number
  revoked_at?: string | null
  revoked_reason?: string
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
  /** Attempts whose written answers are waiting to be marked. */
  awaiting_review: number
  average_best_score: number | null
}

export interface QuizLearnerRow {
  user_id: number
  name: string
  email: string
  state: ActivityStatus
  /** A written attempt is waiting to be marked (it has no score yet). */
  awaiting_review?: boolean
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

// ------------------------------------------------------- practice scenarios

export type ScenarioStatus = 'draft' | 'approved' | 'retired'

export interface PracticeScenario {
  id: number
  topic: string
  topic_label: string
  persona_type: string
  issue_summary: string
  opening_message: string
  personality_notes: string
  doc_hints: string[]
  reference_answer: string
  doc_url: string
  status: ScenarioStatus
  source: ScenarioSource
  created_by: string | null
  approved_by: string | null
  approved_at: string | null
  created_at: string
  uses: number
  /** Past-query imports: the Zendesk ticket it came from (trainers only). */
  source_ticket_id: string | null
  /** Approved by the strict automatic checks rather than a person. */
  auto_approved: boolean
  /** Why a trainer should look again (e.g. several learners skipped it). */
  review_note: string
  import_run: number | null
  /** How it is going in practice. */
  skips: Partial<Record<SkipReasonKey, number>>
  finished: number
  average: number | null
}

export type ScenarioSource = 'generated' | 'manual' | 'seed' | 'zendesk'
export type SkipReasonKey = 'duplicate' | 'unclear' | 'not_relevant'

export interface ZendeskStatus {
  configured: boolean
  import_enabled: boolean
  signoff_recorded: boolean
  audited_at: string | null
  audit: { examined?: number; accepted?: number; reasons?: Record<string, number> }
  /** Why an import can't run right now (null = it can). */
  blocked_reason: string | null
  auto_approve: { on: boolean; setting: boolean; master: boolean }
}

/** How many questions learners can get, against how many we want. `empty` = nobody can start. */
export interface BankStatus {
  approved: number
  drafts: number
  target: number
  state: 'empty' | 'low' | 'ok'
}

export interface TopUpStatus {
  /** On right now (the server switch AND the Console switch). */
  on: boolean
  setting: boolean
  master: boolean
  /** Past tickets looked at per night. */
  count: number
  next_run_at: string
  last_check: { at: string; outcome: 'queued' | 'skipped'; reason: string } | null
  paused: boolean
}

export interface PracticeOptions {
  topics: { key: string; label: string }[]
  personas: string[]
  model_ready: boolean
  counts: Partial<Record<ScenarioStatus, number>>
  zendesk: ZendeskStatus
  bank: BankStatus
  topup: TopUpStatus
  skips_allowed: number
  import_max: number
}

export interface ScenarioImportRow {
  id: number
  state: 'queued' | 'running' | 'done' | 'failed'
  state_label: string
  requested: number
  topic: string
  examined: number
  approved: number
  drafted: number
  duplicates: number
  failed: number
  rejected: Record<string, number>
  auto_approve: boolean
  error: string
  started_by: string | null
  trigger: 'manual' | 'scheduled'
  created_at: string
  finished_at: string | null
  /** Still approved automatically right now (what "send back" would undo). */
  approved_now: number
}

export type ScenarioFields = Partial<
  Pick<
    PracticeScenario,
    'topic' | 'persona_type' | 'issue_summary' | 'opening_message' | 'personality_notes' | 'doc_hints' | 'reference_answer' | 'doc_url'
  >
>

export interface TranscriptTurn {
  seq: number
  role: 'customer' | 'intern'
  text: string
  at: string
  action: string
  tat_seconds: number | null
  scores: {
    communication: number
    empathy: number
    accuracy: number
    concreteness: number
    tat: number
    tat_seconds: number
    notes: Record<string, string>
    docs_relevance: number | null
    flags: string[]
  } | null
  job_state: string
  job_error: string
}

export interface PracticeTranscript {
  id: number
  learner: { id: number; name: string }
  activity: { id: number; title: string }
  state: string
  preview: boolean
  repeated: boolean
  abandon_reason: string
  scenario: Record<string, unknown> & { issue_summary?: string; opening_message?: string; persona_type?: string; topic?: string }
  started_at: string
  finished_at: string | null
  tokens_used: number
  models: { customer: string | null; evaluator: string | null }
  turns: TranscriptTurn[]
  result: TrainerSimResult | null
}

// -------------------------------------------------- mentor-rated simulations

export interface Person {
  id: number
  name: string
  email: string
}

export type Route = 'mine' | 'pool' | 'escalated' | 'routed'
export type CaseStatus =
  | 'not_submitted'
  | 'waiting'
  | 'changes_requested'
  | 'passed'
  | 'waived'
  | 'not_passed'


export interface RatingRow {
  /** A simulation hand-in, or a quiz attempt whose written answers wait for marks. */
  kind?: 'sim' | 'quiz'
  id: number
  learner: Person
  activity: { id: number; title: string }
  course: string
  revision: number
  submitted_at: string
  late: boolean
  review_due_at: string
  review_overdue: boolean
  route: Route
  assigned_mentor: string | null
  claimed_by: string | null
  claimed_by_me: boolean
  needs_attention: boolean
  can_rate: boolean
  /** The viewer's own work: listed, but never theirs to rate. */
  own: boolean
}

export interface CaseRow {
  case_id: number
  learner: Person
  activity: { id: number; title: string }
  course: string
  status: CaseStatus
  due_at: string | null
  overdue: boolean
  revisions: number
  unsuccessful: number
  needs_attention: boolean
}

export interface RatingQueue<Row> extends Paged<Row> {
  tab: 'mine' | 'pool' | 'all' | 'cases'
  counts: { all?: number; mine?: number; pool?: number }
}

export interface RatingCriterion {
  key: string
  label: string
  description: string
  guidance: string
}

export interface ThreadRevision {
  id: number
  revision: number
  state: 'submitted' | 'rated' | 'withdrawn'
  submitted_at: string
  late: boolean
  answer: string
  links: string[]
  files: { id: string; name: string; type: string; size_bytes: number; url: string; inline: boolean }[]
  review_due_at: string
  withdrawn_by: string
  routing: string
  assigned_mentor: string | null
  rating: {
    raw_score: number
    passed: boolean
    comment: string
    rated_at: string | null
    mentor: string | null
    scores: { key: string; label: string; score: number; max: number; feedback: string }[]
  } | null
}

export interface RatingDraft {
  scores: Record<string, number | null>
  feedback: Record<string, string>
  comment: string
  by: string | null
  mine: boolean
}

export interface RatingThread {
  id: number
  revision: number
  state: 'submitted' | 'rated' | 'withdrawn'
  learner: Person
  activity: { id: number; title: string }
  course: string
  scenario: string
  handin: string
  criteria: RatingCriterion[]
  pass_rule: string
  pass_threshold: number
  min_each: number
  mentor_for_course: string | null
  routing: {
    route: Route | null
    assigned_mentor: string | null
    claimed_by: string | null
    claimed_by_me: boolean
    review_due_at: string
    review_overdue: boolean
    escalated: boolean
  }
  access: { can_rate: boolean; reason: string; can_manage: boolean }
  case: {
    id: number
    status: CaseStatus
    due_at: string | null
    due_basis: string
    overdue: boolean
    needs_attention: boolean
    unsuccessful: number
    closed_reason: string
    close_note: string
  }
  draft: RatingDraft | null
  revisions: ThreadRevision[]
}

/** One question of a quiz attempt waiting for marks (or marked). */
export interface QuizReviewQuestion {
  index: number
  kind: 'choice' | 'written'
  text: string
  /** Choice questions: the options, what the learner picked, and whether it was right. */
  choices?: string[]
  picked?: number[]
  correct?: boolean | null
  /** Written questions: what it is worth, what the learner wrote, what to look for, and the
   * marks given so far. */
  max_marks?: number
  answer?: string
  reference_answer?: string
  key_points?: string
  marks?: number | null
  comment?: string
}

/** The marking page for a quiz attempt with written answers. */
export interface QuizReviewThread {
  kind: 'quiz'
  id: number
  state: 'submitted' | 'rated'
  attempt_no: number
  learner: Person
  activity: { id: number; title: string }
  course: string
  pass_threshold: number
  points_possible: number
  points_needed: number
  auto: { earned: number; possible: number }
  questions: QuizReviewQuestion[]
  mentor_for_course: string | null
  routing: RatingThread['routing']
  access: RatingThread['access']
  result: {
    marked_by: string | null
    marked_at: string | null
    score: number | null
    passed: boolean | null
    comment: string
  } | null
  attempts: { number: number; score: number; passed: boolean; submitted_at: string }[]
}

export interface QuizRatingBody {
  marks: Record<string, number>
  comments: Record<string, string>
  comment: string
}

export interface RatingBody {
  scores: Record<string, number | null>
  feedback: Record<string, string>
  comment: string
}

export interface RatingStats {
  window_days: number
  rated: number
  median_hours: number | null
  waiting: number
  waiting_overdue: number
  escalated: number
  mentors: { id: number; name: string; rated: number; median_hours: number; reviewed_late: number }[]
}

/** A mentor-rated simulation as a trainer sees it on a learner's page. */
export interface RatedOverview {
  case_id: number
  status: CaseStatus
  revisions: number
  unsuccessful: number
  needs_attention: boolean
  due_at: string | null
  due_basis: string
  overdue: boolean
  last_score: number | null
  closed_reason: string
  close_note: string
  waiting: {
    id: number
    review_due_at: string
    review_overdue: boolean
    escalated: boolean
    assigned_mentor: string | null
  } | null
}

// -------------------------------------------------------------- enrollment

export type EnrollmentState = 'active' | 'withdrawn'

export interface EnrollmentRow {
  id: number
  user: Person
  course: { id: number; title: string; archived: boolean }
  /** The version they are on; `older` when a newer one has been published since. */
  version: {
    id: number
    number: number
    latest_number: number | null
    older: boolean
  }
  program: { id: number; name: string } | null
  mentor: Person | null
  /** How many of the course's modules they get. */
  modules: { enabled: number; total: number }
  state: EnrollmentState
  source: string
  enrolled_at: string
  withdrawn_at: string | null
  withdrawn_reason: string
}

export interface EnrollOptions {
  courses: {
    id: number
    title: string
    modules: { id: number; title: string }[]
  }[]
  programs: { id: number; name: string; course_ids: number[] }[]
  mentors: Person[]
}

/** One learner's modules on one course: what the course has and what is on for them. */
export interface EnrollmentModules {
  active: boolean
  modules: { id: number; title: string; enabled: boolean }[]
}

export interface PickPerson extends Person {
  on_course: boolean
}

/** What happened to one person in an enroll request. */
export interface EnrollResult {
  user: Person
  outcome: 'enrolled' | 'reactivated' | 'already' | 'failed' | 'program'
  detail?: string
  courses?: { course_id: number; outcome: string; detail: string }[]
}

export interface BulkRow {
  line: number
  email: string
  mentor_email: string
  status: string
  label: string
  detail: string
  user: Person | null
  courses: { id: number; state: string; detail: string }[]
}

export interface BulkReply {
  applied: boolean
  summary: Record<string, number>
  rows: BulkRow[]
}

export interface ProgramCourseRow {
  course_id: number
  title: string
  required: boolean
  published: boolean
  archived: boolean
}

export interface ProgramRow {
  id: number
  name: string
  description: string
  starts_on: string | null
  ends_on: string | null
  archived: boolean
  members: number
  courses: ProgramCourseRow[]
}

export interface ProgramBody {
  name: string
  description: string
  starts_on: string | null
  ends_on: string | null
  courses: { course_id: number; required: boolean }[]
}

export type MoveStatus = 'preserved' | 'changed' | 'added'

export interface MoveActivity {
  id: number
  title: string
  type: string
  status: MoveStatus
  work: string[]
  has_work: boolean
  /** Which parts of a changed activity differ (field names, "attempts", "pass mark"). */
  fields: string[]
  conflict: boolean
  carried: boolean
  can_carry: boolean
}

export interface MoveLesson {
  id: number
  title: string
  module: string
  /** What happens to their tick on this lesson, when they had one. */
  outcome: 'kept' | 'awaiting' | 'reopened' | 'left' | null
  activities: MoveActivity[]
}

export interface MovePreview {
  blockers: string[]
  can_apply: boolean
  from: { id: number; number: number }
  to: { id: number; number: number } | null
  counts?: {
    preserved: number
    preserved_untouched: number
    changed: number
    changed_carried: number
    changed_with_work: number
    added: number
    removed: number
    removed_with_work: number
    lessons_kept: number
    lessons_awaiting: number
    lessons_reopened: number
    lessons_left: number
    modules_new: number
    modules_new_off: number
  }
  /** The newest version's modules: `new` ones can be switched off here; `off` ones stay off. */
  modules?: {
    id: number
    title: string
    status: 'on' | 'off' | 'new'
    enabled: boolean
  }[]
  lessons?: MoveLesson[]
  removed?: {
    id: number
    title: string
    type: string
    lesson: string
    has_work: boolean
  }[]
  left_lessons?: { id: number; title: string }[]
}

const send = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
})

export const adminApi = {
  courses: () => request<{ results: CourseOption[] }>(admin('results/courses/')),
  learners: (q: Query) => request<Paged<LearnerRow>>(admin('results/learners/', q)),
  dashboard: (q: Query) => request<DashboardPage>(admin('results/dashboard/', q)),
  /** A plain link: the browser downloads the CSV with the session cookie. */
  dashboardCsvUrl: (q: Query) => admin('results/dashboard/', { ...q, export: 'csv', page: '' }),
  revokeCertificate: (id: number, reason: string) =>
    request<CertificatePage>(admin(`certificates/${id}/revoke/`), send('POST', { reason })),
  restoreCertificate: (id: number) =>
    request<CertificatePage>(admin(`certificates/${id}/restore/`), send('POST')),
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
  practiceOptions: () => request<PracticeOptions>(admin('practice/options/')),
  scenarios: (q: Query) => request<Paged<PracticeScenario>>(admin('practice/scenarios/', q)),
  createScenario: (body: ScenarioFields) =>
    request<PracticeScenario>(admin('practice/scenarios/'), send('POST', body)),
  updateScenario: (id: number, body: ScenarioFields) =>
    request<PracticeScenario>(admin(`practice/scenarios/${id}/`), send('PATCH', body)),
  approveScenario: (id: number) =>
    request<PracticeScenario>(admin(`practice/scenarios/${id}/approve/`), send('POST')),
  retireScenario: (id: number) =>
    request<PracticeScenario>(admin(`practice/scenarios/${id}/retire/`), send('POST')),
  restoreScenario: (id: number) =>
    request<PracticeScenario>(admin(`practice/scenarios/${id}/restore/`), send('POST')),
  generateScenarios: (body: { count: number; topic?: string; persona?: string }) =>
    request<{ detail: string }>(admin('practice/scenarios/generate/'), send('POST', body)),
  imports: () => request<{ results: ScenarioImportRow[] }>(admin('practice/imports/')),
  startImport: (body: { count: number; topic?: string }) =>
    request<ScenarioImportRow>(admin('practice/imports/'), send('POST', body)),
  revertImport: (id: number) =>
    request<ScenarioImportRow & { sent_back: number }>(
      admin(`practice/imports/${id}/revert/`),
      send('POST'),
    ),
  setAutoApprove: (on: boolean) =>
    request<ZendeskStatus['auto_approve']>(
      admin('practice/settings/'),
      send('PATCH', { auto_approve_enabled: on }),
    ),
  setTopUp: (on: boolean) =>
    request<TopUpStatus>(admin('practice/top-up/'), send('PATCH', { enabled: on })),
  ratingsQueue: <Row = RatingRow>(q: Query) => request<RatingQueue<Row>>(admin('ratings/queue/', q)),
  ratingThread: (id: number | string) => request<RatingThread>(admin(`ratings/submissions/${id}/`)),
  claimRating: (id: number) =>
    request<RatingThread>(admin(`ratings/submissions/${id}/claim/`), send('POST')),
  releaseRating: (id: number) =>
    request<RatingThread>(admin(`ratings/submissions/${id}/release/`), send('POST')),
  reassignRating: (id: number, mentorId: number | null) =>
    request<RatingThread>(admin(`ratings/submissions/${id}/reassign/`), send('POST', { mentor_id: mentorId })),
  draftRating: (id: number, body: Partial<RatingBody>) =>
    request<RatingThread>(admin(`ratings/submissions/${id}/draft/`), send('POST', body)),
  rate: (id: number, body: RatingBody) =>
    request<RatingThread>(admin(`ratings/submissions/${id}/rate/`), send('POST', body)),
  quizReviewThread: (id: number | string) =>
    request<QuizReviewThread>(admin(`ratings/quiz-reviews/${id}/`)),
  claimQuizReview: (id: number) =>
    request<QuizReviewThread>(admin(`ratings/quiz-reviews/${id}/claim/`), send('POST')),
  releaseQuizReview: (id: number) =>
    request<QuizReviewThread>(admin(`ratings/quiz-reviews/${id}/release/`), send('POST')),
  reassignQuizReview: (id: number, mentorId: number | null) =>
    request<QuizReviewThread>(
      admin(`ratings/quiz-reviews/${id}/reassign/`),
      send('POST', { mentor_id: mentorId }),
    ),
  rateQuizReview: (id: number, body: QuizRatingBody) =>
    request<QuizReviewThread>(admin(`ratings/quiz-reviews/${id}/rate/`), send('POST', body)),
  caseAction: (id: number, action: 'extend' | 'waive' | 'close' | 'reopen', body: { reason: string; days?: number }) =>
    request<{ case: { id: number; status: CaseStatus; due_at: string | null; overdue: boolean } }>(
      admin(`ratings/cases/${id}/${action}/`),
      send('POST', body),
    ),
  ratingMentors: (learnerId?: number) =>
    request<{ results: Person[] }>(admin('ratings/mentors/', { learner: learnerId })),
  ratingStats: () => request<RatingStats>(admin('ratings/stats/')),
  transcript: (id: number | string) =>
    request<PracticeTranscript>(admin(`results/sessions/${id}/`)),
  enrollOptions: () => request<EnrollOptions>(admin('enrollments/options/')),
  enrollPeople: (q: Query) => request<{ results: PickPerson[] }>(admin('enrollments/people/', q)),
  enrollments: (q: Query) => request<Paged<EnrollmentRow>>(admin('enrollments/', q)),
  enroll: (body: {
    user_ids: number[]
    course_id?: number
    program_id?: number
    mentor_id?: number | null
    module_ids?: number[]
  }) => request<{ results: EnrollResult[] }>(admin('enrollments/'), send('POST', body)),
  bulkEnroll: (body: {
    text: string
    course_id?: number
    program_id?: number
    mentor_id?: number | null
    module_ids?: number[]
    apply: boolean
  }) => request<BulkReply>(admin('enrollments/bulk/'), send('POST', body)),
  withdraw: (id: number, reason: string) =>
    request<EnrollmentRow>(admin(`enrollments/${id}/withdraw/`), send('POST', { reason })),
  reenroll: (id: number) =>
    request<EnrollmentRow>(admin(`enrollments/${id}/reenroll/`), send('POST')),
  setMentor: (id: number, mentorId: number | null) =>
    request<EnrollmentRow>(
      admin(`enrollments/${id}/mentor/`),
      send('POST', { mentor_id: mentorId }),
    ),
  setGroup: (id: number, programId: number | null) =>
    request<EnrollmentRow>(
      admin(`enrollments/${id}/group/`),
      send('POST', { program_id: programId }),
    ),
  enrollmentModules: (id: number) =>
    request<EnrollmentModules>(admin(`enrollments/${id}/modules/`)),
  setModules: (id: number, moduleIds: number[]) =>
    request<EnrollmentRow>(
      admin(`enrollments/${id}/modules/`),
      send('POST', { module_ids: moduleIds }),
    ),
  movePreview: (id: number, carry: number[], newModulesOff: number[] = []) =>
    request<MovePreview>(
      admin(`enrollments/${id}/migration/`),
      send('POST', { carry, new_modules_off: newModulesOff }),
    ),
  move: (id: number, toVersionId: number, carry: number[], newModulesOff: number[] = []) =>
    request<{ result: MovePreview; enrollment: EnrollmentRow }>(
      admin(`enrollments/${id}/migrate/`),
      send('POST', {
        to_version_id: toVersionId,
        carry,
        new_modules_off: newModulesOff,
      }),
    ),
  programs: (archived = false) =>
    request<{ results: ProgramRow[] }>(admin('programs/', { archived: archived ? 1 : undefined })),
  createProgram: (body: ProgramBody) => request<ProgramRow>(admin('programs/'), send('POST', body)),
  updateProgram: (id: number, body: ProgramBody) =>
    request<ProgramRow>(admin(`programs/${id}/`), send('PUT', body)),
  archiveProgram: (id: number) =>
    request<ProgramRow>(admin(`programs/${id}/archive/`), send('POST')),
  restoreProgram: (id: number) =>
    request<ProgramRow>(admin(`programs/${id}/restore/`), send('POST')),
  enrollMissing: (id: number) =>
    request<{
      people: number
      enrolled: number
      skipped: number
      program: ProgramRow
    }>(admin(`programs/${id}/enroll-missing/`), send('POST')),
}
