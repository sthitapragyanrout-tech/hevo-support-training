import { useState } from 'react'

import { DataTable, type Column } from '../../components/DataTable'
import { PageState } from '../../components/PageState'
import { AdminPage, Toolbar } from './AdminPage'
import { adminApi, type QuizRow } from './adminApi'
import { percent } from './format'
import { useQuery } from './useQuery'
import styles from './results.module.css'

const COLUMNS: Column<QuizRow>[] = [
  {
    key: 'quiz',
    header: 'Quiz',
    render: (q) => (
      <span className={styles.person}>
        <strong>{q.title}</strong>
        <span className={styles.sub}>
          {q.course} · {q.lesson}
        </span>
      </span>
    ),
  },
  { key: 'learners', header: 'Learners', align: 'end', render: (q) => q.learners },
  { key: 'passed', header: 'Passed', align: 'end', render: (q) => q.passed },
  { key: 'not', header: 'Not passed', align: 'end', hideOnMobile: true, render: (q) => q.not_passed },
  { key: 'progress', header: 'In progress', align: 'end', hideOnMobile: true, render: (q) => q.in_progress },
  { key: 'avg', header: 'Average best score', align: 'end', render: (q) => percent(q.average_best_score) },
]

export function QuizzesPage() {
  const [course, setCourse] = useState('')
  const [page, setPage] = useState(1)

  const courses = useQuery(() => adminApi.courses(), 'courses')
  const query = { course, page }
  const quizzes = useQuery(() => adminApi.quizzes(query), JSON.stringify(query))

  return (
    <AdminPage eyebrow="Results" title="Quizzes" hint="How each quiz is going across learners.">
      <Toolbar>
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
      {quizzes.loading ? (
        <PageState kind="loading" />
      ) : quizzes.error || !quizzes.data ? (
        <PageState kind="error" title="Couldn’t load quizzes" onRetry={quizzes.reload}>
          {quizzes.error}
        </PageState>
      ) : (
        <DataTable
          label="Quizzes"
          columns={COLUMNS}
          rows={quizzes.data.results}
          rowKey={(q) => q.id}
          rowHref={(q) => `/admin/results/quizzes/${q.id}`}
          meta={quizzes.data}
          onPage={setPage}
          busy={quizzes.refreshing}
          empty="No published quizzes yet."
        />
      )}
    </AdminPage>
  )
}
