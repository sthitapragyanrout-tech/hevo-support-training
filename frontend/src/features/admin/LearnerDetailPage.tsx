import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { PageState } from '../../components/PageState'
import { useCan } from '../../lib/capabilities'
import { CAN } from '../../lib/capabilityKeys'
import { ConfirmDialog } from '../studio/ConfirmDialog'
import { AdminPage } from './AdminPage'
import { adminApi, type LearnerActivity, type LearnerDetail } from './adminApi'
import { CaseActions } from './CaseActions'
import { formatDateTime, percent, statusLabel, typeLabel, untilText } from './format'
import { useQuery } from './useQuery'
import styles from './results.module.css'

const RATED_STATUS: Record<string, string> = {
  not_submitted: 'Not handed in',
  waiting: 'Waiting for a mentor',
  changes_requested: 'Changes requested',
  passed: 'Passed',
  waived: 'Waived',
  not_passed: 'Closed, not passed',
}

export function LearnerDetailPage() {
  const { userId = '' } = useParams()
  const canReset = useCan(CAN.manageAttempts)
  const canManageReviews = useCan(CAN.manageReviews)
  const canReview = useCan(CAN.rateSimulations)
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
                    {a.lesson} · {typeLabel(a.type)} ·{' '}
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
                {a.watch && (
                  <span className={styles.score}>
                    {a.watch.watched_fraction === null
                      ? a.state === 'completed'
                        ? 'Confirmed by the learner'
                        : 'Not confirmed yet'
                      : `Watched ${percent(a.watch.watched_fraction)}`}
                    {a.watch.needs_review && (
                      <span className={styles.sub}>
                        Worth a look: {a.watch.reasons.join('; ').toLowerCase()}
                      </span>
                    )}
                  </span>
                )}
                {a.sim && (
                  <span className={styles.score}>
                    {a.sim.finished === 0
                      ? 'No tickets finished yet'
                      : `${a.sim.finished} of ${a.sim.required} tickets · average ${Number((a.sim.average_raw ?? 0).toFixed(2))} / 5`}
                    <span className={styles.sub}>
                      {a.sim.skips > 0 ? `${a.sim.skips} ${a.sim.skips === 1 ? 'question' : 'questions'} skipped` : 'none skipped'}
                    </span>
                  </span>
                )}
                {a.sim && a.sim.sessions.length > 0 && (
                  <ol className={styles.attempts} aria-label={`Practice tickets for ${a.title}`}>
                    {a.sim.sessions.map((t, i) => (
                      <li key={t.id}>
                        <Link to={`/admin/results/sessions/${t.id}`}>
                          {t.abandon_reason === 'skipped'
                            ? 'Skipped question'
                            : `Ticket ${a.sim!.sessions.slice(0, i + 1).filter((x) => x.abandon_reason !== 'skipped').length}`}
                        </Link>
                        <strong>{t.raw === null ? '—' : `${Number(t.raw.toFixed(2))} / 5`}</strong>
                        <span className={t.passed ? styles.s_completed : styles.sub}>
                          {t.state === 'finished'
                            ? t.passed
                              ? 'Above the pass mark'
                              : 'Below the pass mark'
                            : t.state === 'abandoned'
                              ? t.abandon_reason === 'skipped'
                                ? `Skipped${t.skip_reason ? ` (${t.skip_reason.replace(/_/g, ' ')})` : ''}`
                                : 'Ended without a score'
                              : 'In progress'}
                          {t.repeated ? ' · seen before' : ''}
                        </span>
                        <span className={styles.sub}>
                          {formatDateTime(t.started_at)}
                          {t.needs_review ? ` · worth a look: ${t.reasons.join(', ').replace(/_/g, ' ')}` : ''}
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
                {a.rated && (
                  <span className={styles.score}>
                    {RATED_STATUS[a.rated.status]}
                    <span className={styles.sub}>
                      {a.rated.revisions} {a.rated.revisions === 1 ? 'revision' : 'revisions'}
                      {a.rated.last_score != null ? ` · last rated ${Number(a.rated.last_score.toFixed(2))} / 5` : ''}
                    </span>
                    {a.rated.due_at && !['passed', 'waived', 'not_passed'].includes(a.rated.status) && (
                      <span className={styles.sub}>
                        {a.rated.overdue ? 'Overdue — was due ' : 'Due '}
                        {formatDateTime(a.rated.due_at)}
                      </span>
                    )}
                    {a.rated.needs_attention && (
                      <span className={styles.sub}>
                        Needs attention: {a.rated.unsuccessful} reviews have asked for changes
                      </span>
                    )}
                    {a.rated.closed_reason && a.rated.close_note && (
                      <span className={styles.sub}>Note: {a.rated.close_note}</span>
                    )}
                  </span>
                )}
                {a.rated?.waiting && (
                  <span className={styles.sub}>
                    Waiting for a review — {untilText(a.rated.waiting.review_due_at).text}
                    {a.rated.waiting.escalated ? ' · open to any mentor' : a.rated.waiting.assigned_mentor ? ` · with ${a.rated.waiting.assigned_mentor}` : ' · in the shared pool'}
                    {(canReview || canManageReviews) && (
                      <>
                        {' · '}
                        <Link to={`/admin/ratings/${a.rated.waiting.id}`}>Open the review</Link>
                      </>
                    )}
                  </span>
                )}
                {a.rated && canManageReviews && (
                  <CaseActions caseId={a.rated.case_id} status={a.rated.status} onDone={() => reload()} />
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
