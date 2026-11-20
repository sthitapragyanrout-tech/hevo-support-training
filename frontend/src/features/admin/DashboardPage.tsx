import { useState } from 'react'

import { DataTable, type Column } from '../../components/DataTable'
import { PageState } from '../../components/PageState'
import { ProgressBar } from '../../components/ProgressBar'
import { AdminPage, Toolbar } from './AdminPage'
import { adminApi, type DashboardRow } from './adminApi'
import { formatWhen } from './format'
import { useDebounced, useQuery } from './useQuery'
import results from './results.module.css'
import styles from './DashboardPage.module.css'

const pct = (n: number) => `${Math.round(n * 100)}%`

/** The sorts people ask for most, by name; a column header click sets the same thing. */
const SORTS: [string, string][] = [
  ['name', 'Name, A to Z'],
  ['-progress', 'Progress, most first'],
  ['progress', 'Progress, least first'],
  ['-quiz', 'Quiz score, highest first'],
  ['quiz', 'Quiz score, lowest first'],
  ['-score', 'Course score, highest first'],
  ['score', 'Course score, lowest first'],
  ['-last', 'Last activity, newest first'],
]

const COLUMNS: Column<DashboardRow>[] = [
  {
    key: 'name',
    header: 'Employee',
    sort: 'name',
    render: (r) => (
      <span className={results.person}>
        <strong>{r.name}</strong>
        {r.name !== r.email && <span className={results.sub}>{r.email}</span>}
      </span>
    ),
  },
  {
    key: 'emp',
    header: 'Emp ID',
    sort: 'emp',
    hideOnMobile: true,
    render: (r) => r.employee_id ?? '—',
  },
  { key: 'course', header: 'Course', sort: 'course', render: (r) => r.course.title },
  {
    key: 'group',
    header: 'Group',
    sort: 'group',
    render: (r) => r.group?.name ?? '—',
  },
  {
    key: 'progress',
    header: 'Progress',
    sort: 'progress',
    render: (r) =>
      r.lessons_done === 0 ? (
        // Nothing done yet reads as words, never as an empty bar or 0%.
        <span className={results.sub}>Not started · {r.lessons_total} lessons</span>
      ) : (
        <span className={styles.progress}>
          <span className={styles.progressText}>
            {r.lessons_done} of {r.lessons_total}
          </span>
          <ProgressBar
            value={r.lessons_done}
            max={r.lessons_total}
            label={`${r.name}, ${r.course.title} progress`}
          />
        </span>
      ),
  },
  {
    key: 'quiz',
    header: 'Quiz score',
    sort: 'quiz',
    align: 'end',
    render: (r) => (r.quiz_score === null ? '—' : pct(r.quiz_score)),
  },
  {
    key: 'score',
    header: 'Course score',
    sort: 'score',
    align: 'end',
    hideOnMobile: true,
    render: (r) =>
      !r.certificate_on ? (
        <span className={results.sub}>Not set up</span>
      ) : r.course_score === null ? (
        '—'
      ) : (
        <span className={results.person}>
          <span>{pct(r.course_score)}</span>
          <span className={results.sub}>pass mark {r.threshold}%</span>
        </span>
      ),
  },
  {
    key: 'certificate',
    header: 'Certificate',
    render: (r) =>
      r.certificate ? (
        <span className={styles.earned}>Earned</span>
      ) : (
        <span className={results.sub}>—</span>
      ),
  },
  {
    key: 'last',
    header: 'Last activity',
    sort: 'last',
    hideOnMobile: true,
    render: (r) => formatWhen(r.last_activity),
  },
]

/** A header-chosen sort the menu doesn't list by name, e.g. "Group, Z to A". */
function sortName(ordering: string) {
  const key = ordering.replace(/^-/, '')
  const header = COLUMNS.find((c) => c.sort === key)?.header ?? key
  return `${header}, ${ordering.startsWith('-') ? 'descending' : 'ascending'}`
}

/** Everyone on a course now: one row per person per course, sortable by how far they are and
 * how they scored, with a click through to their full record. */
export function DashboardPage() {
  const [search, setSearch] = useState('')
  const [course, setCourse] = useState('')
  const [group, setGroup] = useState('')
  const [certified, setCertified] = useState('')
  const [ordering, setOrdering] = useState('name')
  const [page, setPage] = useState(1)
  const term = useDebounced(search)

  const courses = useQuery(() => adminApi.courses(), 'courses')
  const filters = { search: term, course, group, certified, ordering }
  const query = { ...filters, page }
  const rows = useQuery(() => adminApi.dashboard(query), JSON.stringify(query))
  const filtered = Boolean(term || course || group || certified)
  const reset = (set: (v: string) => void) => (v: string) => {
    set(v)
    setPage(1)
  }

  return (
    <AdminPage
      eyebrow="Results"
      title="Dashboard"
      hint="Everyone on a course now: how far they are, how they scored, and who has earned a certificate."
      actions={
        <>
          <a href={adminApi.dashboardCsvUrl(filters)} className="btn" download>
            Export this list
          </a>
          <a href={adminApi.exportUrl(course || undefined)} className="btn" download>
            Export every attempt
          </a>
        </>
      }
    >
      {rows.data && (
        <dl className={styles.totals}>
          <div>
            <dt>People</dt>
            <dd className="num">{rows.data.totals.learners}</dd>
          </div>
          <div>
            <dt>Enrollments</dt>
            <dd className="num">{rows.data.totals.enrollments}</dd>
          </div>
          <div>
            <dt>Certificates earned</dt>
            <dd className="num">{rows.data.totals.certificates}</dd>
          </div>
          <div>
            <dt>Courses</dt>
            <dd className="num">{rows.data.totals.courses}</dd>
          </div>
        </dl>
      )}

      <Toolbar>
        <input
          type="search"
          className={`input ${results.search}`}
          placeholder="Search by name, email or employee id"
          aria-label="Search people"
          value={search}
          onChange={(e) => reset(setSearch)(e.target.value)}
        />
        <select
          className="input"
          aria-label="Course"
          value={course}
          onChange={(e) => reset(setCourse)(e.target.value)}
        >
          <option value="">All courses</option>
          {courses.data?.results.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
        <select
          className="input"
          aria-label="Group"
          value={group}
          onChange={(e) => reset(setGroup)(e.target.value)}
        >
          <option value="">All groups</option>
          {rows.data?.groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
          <option value="none">No group</option>
        </select>
        <select
          className="input"
          aria-label="Certificate"
          value={certified}
          onChange={(e) => reset(setCertified)(e.target.value)}
        >
          <option value="">Any certificate status</option>
          <option value="yes">Certificate earned</option>
          <option value="no">Not earned yet</option>
        </select>
        <select
          className="input"
          aria-label="Sort by"
          value={ordering}
          onChange={(e) => reset(setOrdering)(e.target.value)}
        >
          {SORTS.map(([value, text]) => (
            <option key={value} value={value}>
              Sort: {text}
            </option>
          ))}
          {!SORTS.some(([value]) => value === ordering) && (
            <option value={ordering}>Sort: {sortName(ordering)}</option>
          )}
        </select>
      </Toolbar>

      {rows.loading ? (
        <PageState kind="loading" />
      ) : rows.error || !rows.data ? (
        <PageState kind="error" title="Couldn’t load the dashboard" onRetry={rows.reload}>
          {rows.error}
        </PageState>
      ) : (
        <DataTable
          label="Learners on courses"
          columns={COLUMNS}
          rows={rows.data.results}
          rowKey={(r) => r.enrollment_id}
          rowHref={(r) => `/admin/results/learners/${r.user_id}?course=${r.course.id}`}
          meta={rows.data}
          ordering={ordering}
          onOrdering={(o) => {
            setOrdering(o)
            setPage(1)
          }}
          onPage={setPage}
          busy={rows.refreshing}
          empty={filtered ? 'Nobody matches.' : 'Nobody is enrolled on a course yet.'}
        />
      )}
    </AdminPage>
  )
}
