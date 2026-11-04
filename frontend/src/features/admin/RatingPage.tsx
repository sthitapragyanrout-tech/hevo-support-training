import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Dialog } from '../../components/Dialog'
import { PageState } from '../../components/PageState'
import { ApiError } from '../../lib/api'
import { AdminPage } from './AdminPage'
import { adminApi, type Person, type RatingThread, type ThreadRevision } from './adminApi'
import { CaseActions } from './CaseActions'
import { estimate } from './ratingMath'
import { formatDateTime, untilText } from './format'
import { useQuery } from './useQuery'
import styles from './ratings.module.css'

const SCALE = [1, 2, 3, 4, 5]
const size = (bytes: number) =>
  bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
const out5 = (n: number) => `${Number(n.toFixed(2))} / 5`

export function RatingPage() {
  const { submissionId } = useParams()
  return <Workspace key={submissionId} id={submissionId ?? ''} />
}

function Workspace({ id }: { id: string }) {
  const load = useQuery(() => adminApi.ratingThread(id), id)
  const [thread, setThread] = useState<RatingThread | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const data = thread ?? load.data

  if (load.loading) return <PageState kind="loading" />
  if (load.error || !data)
    return (
      <PageState kind="error" title="Couldn’t open this submission" onRetry={load.reload}>
        {load.errorStatus === 404 ? 'It doesn’t exist, or it isn’t yours to see.' : load.error}
      </PageState>
    )
  return (
    <Thread
      t={data}
      note={note}
      onThread={(next, message) => {
        setThread(next)
        if (message) setNote(message)
      }}
      reload={() => adminApi.ratingThread(id).then((next) => setThread(next))}
    />
  )
}

function route(t: RatingThread): string {
  const r = t.routing
  if (t.state !== 'submitted') return ''
  if (r.claimed_by) return r.claimed_by_me ? 'You are rating this.' : `${r.claimed_by} is rating this.`
  if (r.escalated) return `The review is overdue, so any mentor may take it${r.assigned_mentor ? ` (it was with ${r.assigned_mentor})` : ''}.`
  if (r.route === 'pool') return 'In the shared pool: any mentor may take it.'
  if (r.route === 'mine') return 'Assigned to you.'
  return r.assigned_mentor ? `With ${r.assigned_mentor}.` : ''
}

function Thread({
  t,
  note,
  onThread,
  reload,
}: {
  t: RatingThread
  note: string | null
  onThread: (next: RatingThread, message?: string) => void
  reload: () => Promise<void>
}) {
  const due = untilText(t.routing.review_due_at)
  const open = t.state === 'submitted'
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(task: () => Promise<RatingThread>, message?: string) {
    setBusy(true)
    setProblem(null)
    try {
      onThread(await task(), message)
    } catch (err) {
      setProblem(err instanceof ApiError && err.message ? err.message : 'That didn’t work. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AdminPage
      eyebrow="Review"
      title={`${t.activity.title} — revision ${t.revision}`}
      hint={
        <>
          {t.learner.name} · {t.course} · <Link to="/admin/ratings">Back to the queue</Link>
        </>
      }
      actions={
        t.access.can_manage ? (
          <CaseActions
            caseId={t.case.id}
            status={t.case.status}
            onDone={(message) => void reload().then(() => onThread(t, message))}
          />
        ) : undefined
      }
    >
      {note && (
        <p role="status" className={styles.note}>
          {note}
        </p>
      )}
      {problem && (
        <p className={styles.problem} role="alert">
          {problem}
        </p>
      )}
      <div className={styles.page}>
        <div className={styles.col}>
          {open && (
            <p className={styles.banner} role="status">
              {route(t)} Review <span className={due.overdue ? styles.overdue : undefined}>{due.overdue ? due.text : `due ${due.text}`}</span> (
              {formatDateTime(t.routing.review_due_at)}).
              {t.case.needs_attention && ` ${t.case.unsuccessful} reviews have asked for changes — this one needs attention.`}
            </p>
          )}
          <section className={styles.section} aria-label="The task">
            <h2>The task</h2>
            <p className={styles.prose}>{t.scenario}</p>
            {t.handin && <p className={styles.prose}>{t.handin}</p>}
          </section>
          <section className={styles.section} aria-label="The rubric">
            <h2>The rubric</h2>
            {t.criteria.map((c) => (
              <p key={c.key} className={styles.criterion}>
                <strong>{c.label}</strong>
                {c.description ? ` — ${c.description}` : ''}
                {c.guidance && (
                  <span className={styles.guidance}>
                    For raters: {c.guidance}
                  </span>
                )}
              </p>
            ))}
            <p className={styles.hint}>{t.pass_rule}</p>
          </section>
          <section className={styles.section} aria-label="The learner’s work">
            <h2>The learner’s work</h2>
            <ol className={styles.thread}>
              {[...t.revisions].reverse().map((r) => (
                <Revision key={r.id} r={r} open={r.id === t.id} />
              ))}
            </ol>
          </section>
        </div>

        <aside className={styles.col} aria-label="Rating">
          {open && t.access.can_rate ? (
            <RatingForm t={t} busy={busy} run={run} />
          ) : (
            <div className={styles.form}>
              <p>{open ? t.access.reason : outcome(t)}</p>
              {open && <Manage t={t} run={run} busy={busy} />}
            </div>
          )}
          {open && t.access.can_rate && <Manage t={t} run={run} busy={busy} />}
        </aside>
      </div>
    </AdminPage>
  )
}

function outcome(t: RatingThread): string {
  const mine = t.revisions.find((r) => r.id === t.id)
  if (mine?.state === 'rated' && mine.rating)
    return `Rated ${out5(mine.rating.raw_score)} by ${mine.rating.mentor ?? 'a mentor'} — ${mine.rating.passed ? 'passed' : 'changes requested'}.`
  if (mine?.state === 'withdrawn') return 'This submission was withdrawn.'
  return ''
}

function Revision({ r, open }: { r: ThreadRevision; open: boolean }) {
  const head =
    r.state === 'withdrawn'
      ? `Withdrawn${r.withdrawn_by ? ` (${r.withdrawn_by === 'closed' ? 'case closed' : r.withdrawn_by})` : ''}`
      : r.state === 'submitted'
        ? 'Waiting for a rating'
        : r.rating
          ? `${r.rating.passed ? 'Passed' : 'Changes requested'} · ${out5(r.rating.raw_score)}`
          : 'Rated'
  return (
    <li>
      <details open={open}>
        <summary>
          <strong>Revision {r.revision}</strong> · {formatDateTime(r.submitted_at)}
          {r.late ? ' · handed in late' : ''} · {head}
        </summary>
        <p className={styles.prose}>{r.answer}</p>
        {r.links.length > 0 && (
          <ul className={styles.links} aria-label="Links">
            {r.links.map((l) => (
              <li key={l}>
                <a href={l} target="_blank" rel="noopener noreferrer">
                  {l}
                </a>
              </li>
            ))}
          </ul>
        )}
        {r.files.length > 0 && (
          <ul className={styles.files} aria-label="Files">
            {r.files.map((f) => (
              <li key={f.id}>
                {f.inline && (
                  <a href={f.url} target="_blank" rel="noopener noreferrer">
                    <img src={f.url} alt={f.name} className={styles.thumb} loading="lazy" />
                  </a>
                )}
                <a href={f.url} target="_blank" rel="noopener noreferrer">
                  {f.name}
                </a>{' '}
                <span className={styles.hint}>· {size(f.size_bytes)}</span>
              </li>
            ))}
          </ul>
        )}
        {r.rating && (
          <>
            <table className="table" style={{ width: '100%' }}>
              <caption className="sr-only">Scores for revision {r.revision}</caption>
              <tbody>
                {r.rating.scores.map((s) => (
                  <tr key={s.key}>
                    <th scope="row" style={{ textAlign: 'left' }}>
                      {s.label}
                    </th>
                    <td>{`${s.score} / ${s.max}`}</td>
                    <td>{s.feedback}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className={styles.prose}>
              <strong>{r.rating.mentor ?? 'A mentor'}:</strong> {r.rating.comment}
            </p>
          </>
        )}
      </details>
    </li>
  )
}

function RatingForm({
  t,
  busy,
  run,
}: {
  t: RatingThread
  busy: boolean
  run: (task: () => Promise<RatingThread>, message?: string) => Promise<void>
}) {
  const [scores, setScores] = useState<Record<string, number | null>>(
    Object.fromEntries(t.criteria.map((c) => [c.key, t.draft?.scores?.[c.key] ?? null])),
  )
  const [feedback, setFeedback] = useState<Record<string, string>>(t.draft?.feedback ?? {})
  const [comment, setComment] = useState(t.draft?.comment ?? '')
  const [confirming, setConfirming] = useState(false)
  const sum = estimate(scores, t.criteria, t.pass_threshold, t.min_each)
  const body = { scores, feedback, comment }

  return (
    <form className={styles.form} onSubmit={(e) => e.preventDefault()} aria-label="Rate this submission">
      {t.draft && !t.draft.mine && (
        <p className={styles.hint}>A draft started by {t.draft.by ?? 'another reviewer'} is filled in. Check it before you submit.</p>
      )}
      {t.criteria.map((c) => (
        <fieldset key={c.key} className={styles.scoreRow}>
          <legend>{c.label}</legend>
          <div className={styles.scale} role="radiogroup" aria-label={`${c.label} score`}>
            {SCALE.map((n) => (
              <label key={n}>
                <input
                  type="radio"
                  name={`score-${c.key}`}
                  value={n}
                  checked={scores[c.key] === n}
                  onChange={() => setScores({ ...scores, [c.key]: n })}
                />
                {n}
              </label>
            ))}
          </div>
          <label htmlFor={`fb-${c.key}`} className="sr-only">
            Feedback on {c.label}
          </label>
          <textarea
            id={`fb-${c.key}`}
            className="input"
            rows={2}
            placeholder="Feedback (optional)"
            value={feedback[c.key] ?? ''}
            onChange={(e) => setFeedback({ ...feedback, [c.key]: e.target.value })}
          />
        </fieldset>
      ))}
      <div>
        <label htmlFor="overall" style={{ fontWeight: 600, fontSize: 'var(--fs-14)' }}>
          Overall comment for the learner
        </label>
        <textarea id="overall" className="input" rows={4} value={comment} onChange={(e) => setComment(e.target.value)} />
      </div>
      <p className={styles.average} role="status">
        {sum
          ? `Average ${out5(sum.raw)} — ${sum.passes ? 'meets' : 'does not meet'} the pass mark. ${sum.below.length ? `Below the minimum: ${sum.below.join(', ')}.` : ''}`
          : 'Score every criterion to see the average.'}
      </p>
      <p className={styles.hint}>{t.pass_rule}</p>
      <div className={styles.actionRow}>
        <button type="button" className="btn" disabled={busy} onClick={() => void run(() => adminApi.draftRating(t.id, body), 'Draft saved.')}>
          Save draft
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || !sum || !comment.trim()}
          onClick={() => setConfirming(true)}
        >
          Submit rating
        </button>
      </div>
      {confirming && (
        <Dialog
          title="Submit this rating?"
          width={460}
          onClose={() => setConfirming(false)}
          actions={
            <>
              <button type="button" className="btn" onClick={() => setConfirming(false)}>
                Keep editing
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy}
                onClick={() => {
                  setConfirming(false)
                  void run(() => adminApi.rate(t.id, body), 'Rating submitted.')
                }}
              >
                Submit it
              </button>
            </>
          }
        >
          {t.learner.name} will see these scores and your comment. A submitted rating can’t be changed.
        </Dialog>
      )}
    </form>
  )
}

function Manage({
  t,
  busy,
  run,
}: {
  t: RatingThread
  busy: boolean
  run: (task: () => Promise<RatingThread>, message?: string) => Promise<void>
}) {
  const [reassigning, setReassigning] = useState(false)
  const holder = t.routing.claimed_by
  if (t.state !== 'submitted') return null
  const canTakeOver = t.access.can_manage && holder && !t.routing.claimed_by_me
  return (
    <div className={styles.actionRow}>
      {t.routing.claimed_by_me && (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void run(() => adminApi.releaseRating(t.id), 'Released.')}>
          Release it
        </button>
      )}
      {canTakeOver && (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void run(() => adminApi.claimRating(t.id), 'You have taken it over.')}>
          Take it over
        </button>
      )}
      {t.access.can_manage && (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setReassigning(true)}>
          Reassign…
        </button>
      )}
      {reassigning && (
        <ReassignDialog
          t={t}
          onClose={() => setReassigning(false)}
          onPick={(id) => {
            setReassigning(false)
            void run(() => adminApi.reassignRating(t.id, id), 'Reassigned.')
          }}
        />
      )}
    </div>
  )
}

function ReassignDialog({ t, onClose, onPick }: { t: RatingThread; onClose: () => void; onPick: (id: number | null) => void }) {
  const mentors = useQuery(() => adminApi.ratingMentors(t.learner.id), `mentors-${t.learner.id}`)
  const [choice, setChoice] = useState('pool')
  const people: Person[] = mentors.data?.results ?? []
  return (
    <Dialog
      title="Reassign this review"
      width={480}
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={() => onPick(choice === 'pool' ? null : Number(choice))}>
            Reassign
          </button>
        </>
      }
    >
      <div className={styles.dialogForm}>
        <p className={styles.hint}>Send just this submission to a mentor, or back to the shared pool. It stays where you put it.</p>
        <label htmlFor="reassign-to" className={styles.field}>
          Send it to
          <select id="reassign-to" className="input" value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="pool">The shared pool</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.email})
              </option>
            ))}
          </select>
        </label>
      </div>
    </Dialog>
  )
}
