import { Link, useParams } from 'react-router-dom'

import { PageState } from '../../components/PageState'
import { SimResults } from '../catalog/activities/SimResults'
import { AdminPage } from './AdminPage'
import { adminApi } from './adminApi'
import { formatDateTime } from './format'
import { useQuery } from './useQuery'
import styles from './practice.module.css'

const DIMS = [
  ['communication', 'Communication'],
  ['empathy', 'Empathy'],
  ['accuracy', 'Accuracy'],
  ['concreteness', 'Concreteness'],
  ['tat', 'Turnaround'],
] as const

/** A trainer's view of one practice ticket: the whole conversation, each reply's
 * scores and the reasons given, and anything flagged for a second look. */
export function SimTranscriptPage() {
  const { sessionId = '' } = useParams()
  const data = useQuery(() => adminApi.transcript(sessionId), sessionId)
  if (data.loading) return <PageState kind="loading" />
  if (data.error || !data.data) {
    return (
      <PageState kind="error" title="Couldn’t load this ticket" onRetry={data.reload}>
        {data.error}
      </PageState>
    )
  }
  const t = data.data
  return (
    <AdminPage
      eyebrow="Results · Practice ticket"
      title={t.scenario.issue_summary ?? 'Practice ticket'}
      hint={
        <>
          {t.learner.name} · {t.activity.title} · started {formatDateTime(t.started_at)} · {t.state}
          {t.repeated ? ' · a scenario they had seen before' : ''}
        </>
      }
      actions={
        <Link to={`/admin/results/learners/${t.learner.id}`} className="btn">
          {t.learner.name}’s results
        </Link>
      }
    >
      {t.result?.needs_review && (
        <p className={styles.flag} role="note">
          Worth a look: {t.result.review_reasons?.join(', ').replace(/_/g, ' ')}.
        </p>
      )}
      <ol className={styles.turns} aria-label="Conversation">
        {t.turns.map((turn) => (
          <li key={turn.seq} className={`${styles.turn} ${turn.role === 'intern' ? styles.turnIntern : ''}`}>
            <p className={styles.turnHead}>
              <span>{turn.role === 'intern' ? t.learner.name : 'Customer'}{turn.action === 'nudge' ? ' (nudge)' : ''}</span>
              <span>{formatDateTime(turn.at)}</span>
            </p>
            <p className={styles.turnBody}>{turn.text}</p>
            {turn.scores && (
              <>
                <ul className={styles.scores} aria-label={`Scores for reply ${turn.seq}`}>
                  {DIMS.map(([key, label]) => (
                    <li key={key}>
                      {label} {turn.scores?.[key]}
                    </li>
                  ))}
                  <li>Took {Math.round((turn.tat_seconds ?? 0) / 60)} min</li>
                  {turn.scores.flags.map((f) => (
                    <li key={f} className={styles.flag}>{f.replace(/_/g, ' ')}</li>
                  ))}
                </ul>
                <p className={styles.notes}>
                  {Object.entries(turn.scores.notes)
                    .filter(([, v]) => v)
                    .map(([k, v]) => `${k.replace('_', ' ')}: ${v}`)
                    .join(' · ')}
                </p>
              </>
            )}
            {turn.job_state === 'failed' && <p className={styles.problem}>Failed: {turn.job_error}</p>}
          </li>
        ))}
      </ol>
      {t.result && (
        <SimResults
          session={{ thread: [] } as never}
          result={t.result}
          canTryAgain={false}
          onTryAgain={() => {}}
          conversation={false}
        />
      )}
      <p className={styles.hint}>
        Models: customer {t.models.customer ?? '—'}, scoring {t.models.evaluator ?? '—'} · {t.tokens_used.toLocaleString()} tokens used.
      </p>
    </AdminPage>
  )
}
