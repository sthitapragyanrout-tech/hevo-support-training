import { useState } from 'react'

import { DataTable, type Column } from '../../components/DataTable'
import { PageState } from '../../components/PageState'
import { AdminPage, Toolbar } from './AdminPage'
import { adminApi, type LearnerRow } from './adminApi'
import { formatWhen } from './format'
import { useDebounced, useQuery } from './useQuery'
import styles from './results.module.css'

const COLUMNS: Column<LearnerRow>[] = [
  {
    key: 'name',
    header: 'Learner',
    sort: 'name',
    render: (l) => (
      <span className={styles.person}>
        <strong>{l.name}</strong>
        {l.name !== l.email && <span className={styles.sub}>{l.email}</span>}
      </span>
    ),
  },
  {
    key: 'lessons',
    header: 'Lessons completed',
    sort: 'lessons',
    align: 'end',
    render: (l) => l.lessons_completed,
  },
  {
    key: 'attempts',
    header: 'Quiz attempts',
    sort: 'attempts',
    align: 'end',
    hideOnMobile: true,
    render: (l) => l.quiz_attempts,
  },
  {
    key: 'last',
    header: 'Last activity',
    hideOnMobile: true,
    render: (l) => formatWhen(l.last_activity),
  },
]

export function LearnersPage() {
  const [search, setSearch] = useState('')
  const [course, setCourse] = useState('')
  const [ordering, setOrdering] = useState('name')
  const [page, setPage] = useState(1)
  const term = useDebounced(search)

  const courses = useQuery(() => adminApi.courses(), 'courses')
  const query = { search: term, course, ordering, page }
  const learners = useQuery(() => adminApi.learners(query), JSON.stringify(query))

  return (
    <AdminPage
      eyebrow="Results"
      title="Learners"
      hint="Who has done what, and how they scored."
      actions={
        <a href={adminApi.exportUrl(course || undefined)} className="btn" download>
          Export CSV
        </a>
      }
    >
      <Toolbar>
        <input
          type="search"
          className={`input ${styles.search}`}
          placeholder="Search by name, email or employee id"
          aria-label="Search learners"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
        />
        <select
          className="input"
          aria-label="Course"
          value={course}
          onChange={(e) => {
            setCourse(e.target.value)
            setPage(1)
          }}
        >
          <option value="">All courses</option>
          {courses.data?.results.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
      </Toolbar>

      {learners.loading ? (
        <PageState kind="loading" />
      ) : learners.error || !learners.data ? (
        <PageState kind="error" title="Couldn’t load learners" onRetry={learners.reload}>
          {learners.error}
        </PageState>
      ) : (
        <DataTable
          label="Learners"
          columns={COLUMNS}
          rows={learners.data.results}
          rowKey={(l) => l.id}
          rowHref={(l) => `/admin/results/learners/${l.id}`}
          meta={learners.data}
          ordering={ordering}
          onOrdering={(o) => {
            setOrdering(o)
            setPage(1)
          }}
          onPage={setPage}
          busy={learners.refreshing}
          empty={term || course ? 'No learners match.' : 'Nobody has started a course yet.'}
        />
      )}
    </AdminPage>
  )
}
