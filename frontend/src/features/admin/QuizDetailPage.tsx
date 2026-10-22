import { Link, useParams } from 'react-router-dom'

import { DataTable, type Column } from '../../components/DataTable'
import { PageState } from '../../components/PageState'
import { AdminPage } from './AdminPage'
import { adminApi, type QuizLearnerRow } from './adminApi'
import { formatWhen, percent, statusLabel } from './format'
import { useQuery } from './useQuery'
import styles from './results.module.css'

export function QuizDetailPage() {
  const { activityId = '' } = useParams()
  const { data, loading, error, errorStatus, reload } = useQuery(
    () => adminApi.quiz(activityId),
    `quiz-${activityId}`,
  )

  if (loading) return <PageState kind="loading" />
  if (errorStatus === 404) return <PageState kind="empty" title="Quiz not found" />
  if (error || !data) {
    return (
      <PageState kind="error" title="Couldn’t load this quiz" onRetry={reload}>
        {error}
      </PageState>
    )
  }

  const columns: Column<QuizLearnerRow>[] = [
    {
      key: 'learner',
      header: 'Learner',
      render: (l) => (
        <span className={styles.person}>
          <strong>{l.name}</strong>
          {l.name !== l.email && <span className={styles.sub}>{l.email}</span>}
        </span>
      ),
    },
    {
      key: 'state',
      header: 'Status',
      render: (l) => (
        <span className={`${styles.status} ${styles[`s_${l.state}`]}`}>
          {statusLabel(l.state, 'mcq')}
        </span>
      ),
    },
    {
      key: 'attempts',
      header: data.max_attempts > 0 ? `Attempts (of ${data.max_attempts})` : 'Attempts',
      align: 'end',
      render: (l) => l.attempts,
    },
    { key: 'best', header: 'Best', align: 'end', render: (l) => percent(l.best_score) },
    { key: 'last', header: 'Last attempt', hideOnMobile: true, render: (l) => formatWhen(l.last_attempt_at) },
  ]

  return (
    <AdminPage
      eyebrow="Results · Quizzes"
      title={data.title}
      hint={`${data.course} · ${data.lesson}`}
      actions={
        <Link to="/admin/results/quizzes" className="btn">
          All quizzes
        </Link>
      }
    >
      <DataTable
        label={`Learners who tried ${data.title}`}
        columns={columns}
        rows={data.learners}
        rowKey={(l) => l.user_id}
        rowHref={(l) => `/admin/results/learners/${l.user_id}`}
        empty="Nobody has tried this quiz yet."
      />
    </AdminPage>
  )
}
