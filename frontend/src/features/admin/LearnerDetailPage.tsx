import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { PageState } from '../../components/PageState'
import { useCan } from '../../lib/capabilities'
import { CAN } from '../../lib/capabilityKeys'
import { ConfirmDialog } from '../studio/ConfirmDialog'
import { AdminPage } from './AdminPage'
import { adminApi, type LearnerActivity, type LearnerDetail } from './adminApi'
import { formatDateTime, percent, statusLabel } from './format'
import { useQuery } from './useQuery'
import styles from './results.module.css'

export function LearnerDetailPage() {
  const { userId = '' } = useParams()
  const canReset = useCan(CAN.manageAttempts)
  const { data, loading, error, errorStatus, reload } = useQuery(
    () => adminApi.learner(userId),
    `learner-${userId}`,
  )
  const [resetting, setResetting] = useState<LearnerActivity | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  if (loading) return <PageState kind="loading" />
  if (errorStatus === 404) return <PageState kind="empty" title="Learner not found" />
  if (error || !data) {
    return (
      <PageState kind="error" title="Couldn’t load this learner" onRetry={reload}>
        {error}
      </PageState>
    )
  }

  async function reset(learner: LearnerDetail, activity: LearnerActivity) {
    setBusy(true)
    setProblem(null)
    try {
      await adminApi.resetAttempts(learner.id, activity.id)
      setResetting(null)
      reload()
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t reset the attempts.')
      setResetting(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AdminPage
      eyebrow="Results · Learners"
      title={data.name}
      hint={
        <>
          {data.email}
          {data.employee_id ? ` · ${data.employee_id}` : ''}
        </>
      }
      actions={
        <Link to="/admin/results/learners" className="btn">
          All learners
        </Link>
      }
    >
      {problem && (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      )}

      {data.courses.length === 0 && (
        <p className={styles.quiet}>{data.name} hasn’t started a course yet.</p>
      )}

      {data.courses.map((course) => (
        <section key={`${course.course_id}-${course.version}`} className={styles.course}>
          <header className={styles.courseHead}>
            <h2>{course.title}</h2>
            <p>
              {course.lessons_completed} of {course.lessons_total} lessons completed
            </p>
          </header>
          <ul className={styles.activities}>
            {course.activities.map((a) => (
              <li key={a.id} className={styles.activity}>
                <div className={styles.activityMain}>
                  <p className={styles.activityTitle}>{a.title}</p>
                  <p className={styles.sub}>
                    {a.lesson} · {a.type === 'mcq' ? 'Quiz' : 'Reading'} ·{' '}
                    {a.required ? 'Required' : 'Optional'}
                  </p>
                </div>
                <span className={`${styles.status} ${styles[`s_${a.state}`]}`}>
                  {statusLabel(a.state, a.type)}
                </span>
                {a.scored && (
                  <span className={styles.score}>
                    {a.best_score === null ? '—' : `Best ${percent(a.best_score)}`}
                    <span className={styles.sub}>
                      {a.attempts.length}
                      {a.max_attempts > 0 ? ` of ${a.max_attempts}` : ''} attempts
                    </span>
                  </span>
                )}
                {a.scored && canReset && a.attempts.length > 0 && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setResetting(a)}
                  >
                    Reset attempts
                  </button>
                )}
                {a.attempts.length > 0 && (
                  <ol className={styles.attempts} aria-label={`Attempts at ${a.title}`}>
                    {a.attempts.map((t) => (
                      <li key={t.number}>
                        <span>Attempt {t.number}</span>
                        <strong>{percent(t.score)}</strong>
                        <span className={t.passed ? styles.s_completed : styles.sub}>
                          {t.correct} of {t.total} · {t.passed ? 'Passed' : 'Not passed'}
                        </span>
                        <span className={styles.sub}>{formatDateTime(t.submitted_at)}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}

      {resetting && (
        <ConfirmDialog
          title="Reset these attempts?"
          confirmLabel="Reset attempts"
          busy={busy}
          onCancel={() => setResetting(null)}
          onConfirm={() => void reset(data, resetting)}
        >
          This deletes {data.name}’s {resetting.attempts.length}{' '}
          {resetting.attempts.length === 1 ? 'attempt' : 'attempts'} at “{resetting.title}”, so they can
          take it again. If a lesson was completed because of this quiz, it is reopened. The reset is
          recorded in the audit log.
        </ConfirmDialog>
      )}
    </AdminPage>
  )
}
