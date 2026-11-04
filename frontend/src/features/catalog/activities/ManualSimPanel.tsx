import { useMemo, useRef, useState } from 'react'

import { Dialog } from '../../../components/Dialog'
import {
  ApiError,
  ratedApi,
  type ActivitySummary,
  type RatedRevision,
  type RatedView,
} from '../../../lib/api'
import styles from './ManualSimActivity.module.css'
import { score, when } from './manualSimFormat'

const KINDS = ['png', 'jpg', 'jpeg', 'webp', 'pdf']
const MB = 1024 * 1024

interface Props {
  activity: ActivitySummary
  /** The learner's own view from the server; null in an author's preview. */
  view: RatedView | null
  preview: boolean
  onChange: (next: RatedView) => void
}

const size = (bytes: number) => (bytes >= MB ? `${(bytes / MB).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`)

/** The work itself: the brief and rubric, where things stand, a form to hand in (or revise),
 * and every earlier revision with its rating. */
export function ManualSimPanel({ activity, view, preview, onChange }: Props) {
  // In an author's preview there is no server view: show the brief from the activity itself.
  const config = view?.config ?? (activity.config as unknown as RatedView['config'])
  const criteria = config.criteria ?? []
  const status = view?.case.status ?? 'not_opened'
  const revisions = view?.revisions ?? []
  const lastLive = [...revisions].reverse().find((r) => r.state !== 'withdrawn')

  return (
    <div className={styles.panel}>
      <section aria-label="The task">
        <h3 className={styles.h}>The task</h3>
        <p className={styles.prose}>{config.scenario}</p>
        {config.handin && (
          <>
            <h3 className={styles.h}>What to hand in</h3>
            <p className={styles.prose}>{config.handin}</p>
          </>
        )}
      </section>

      <section aria-label="How it is rated">
        <h3 className={styles.h}>How it’s rated</h3>
        <ul className={styles.criteria}>
          {criteria.map((c) => (
            <li key={c.key}>
              <strong>{c.label}</strong>
              {c.description ? <span> — {c.description}</span> : null}
            </li>
          ))}
        </ul>
        <p className={styles.note}>
          {(config as { pass_rule?: string }).pass_rule ?? ''}{' '}
          {config.review_hours ? `A mentor aims to review within ${config.review_hours} hours.` : ''}
        </p>
      </section>

      {preview || !view ? (
        <p className={styles.note} role="status">
          This is what learners see. Nothing is recorded in a preview.
        </p>
      ) : (
        <>
          <StatusBlock view={view} onChange={onChange} />
          {view.case.can_submit && (
            <HandIn
              key={`${view.case.revisions}-${view.revisions.length}`}
              activity={activity}
              view={view}
              initial={status === 'changes_requested' ? (lastLive?.answer ?? '') : ''}
              onChange={onChange}
            />
          )}
          {revisions.length > 0 && (
            <section aria-label="Your work so far">
              <h3 className={styles.h}>Your work so far</h3>
              <ol className={styles.history}>
                {[...revisions].reverse().map((r, i) => (
                  <Revision key={r.id} r={r} open={i === 0} />
                ))}
              </ol>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function StatusBlock({ view, onChange }: { view: RatedView; onChange: (next: RatedView) => void }) {
  const c = view.case
  const waiting = view.revisions.find((r) => r.state === 'submitted')
  const [confirming, setConfirming] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const lines: Record<string, string> = {
    not_opened: '',
    not_submitted: c.overdue
      ? `Overdue — this was due ${when(c.due_at)}. You can still hand it in; your mentor will see it was late.`
      : c.due_at
        ? `Due ${when(c.due_at)}.`
        : 'There’s no deadline for this one.',
    waiting: waiting
      ? `Handed in ${when(waiting.submitted_at)}${waiting.late ? ' (late)' : ''}. Waiting for your mentor${waiting.expected_by ? ` — expected by ${when(waiting.expected_by)}` : ''}.`
      : 'Waiting for your mentor.',
    changes_requested: c.overdue
      ? `Changes were requested. Your revision was due ${when(c.due_at)}; you can still hand it in.`
      : `Changes requested. ${c.due_at ? `Hand in a revision by ${when(c.due_at)}.` : 'Revise and hand it in again.'}`,
    passed: 'Passed. Nothing more to do here.',
    waived: 'Your trainer has excused you from this activity.',
    not_passed: 'Your trainer has closed this activity.',
  }

  async function withdraw() {
    if (!waiting) return
    setBusy(true)
    setProblem(null)
    try {
      onChange(await ratedApi.withdraw(waiting.id))
      setConfirming(false)
    } catch (err) {
      setProblem(err instanceof ApiError && err.message ? err.message : 'That didn’t work. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.status} role="status">
      <p className={c.overdue ? styles.overdue : undefined}>{lines[c.status]}</p>
      {problem && (
        <p className={styles.problem} role="alert">
          {problem}
        </p>
      )}
      {c.can_withdraw && (
        <p>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirming(true)}>
            Withdraw and edit
          </button>
        </p>
      )}
      {confirming && (
        <Dialog
          title="Take this back?"
          width={440}
          onClose={() => setConfirming(false)}
          actions={
            <>
              <button type="button" className="btn" onClick={() => setConfirming(false)}>
                Keep it
              </button>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void withdraw()}>
                {busy ? 'Working…' : 'Withdraw it'}
              </button>
            </>
          }
        >
          No mentor has started on it, so you can take it back, change it and hand it in again. It
          won’t count as an attempt and your deadline doesn’t move.
        </Dialog>
      )}
    </div>
  )
}

function HandIn({
  activity,
  view,
  initial,
  onChange,
}: {
  activity: ActivitySummary
  view: RatedView
  initial: string
  onChange: (next: RatedView) => void
}) {
  const { limits, config } = view
  const [answer, setAnswer] = useState(initial)
  const [links, setLinks] = useState<string[]>([])
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const picker = useRef<HTMLInputElement>(null)
  const revising = view.case.status === 'changes_requested'

  const fileProblem = useMemo(() => {
    if (files.length > limits.max_files) return `Attach at most ${limits.max_files} files.`
    const tooBig = files.find((f) => f.size > limits.max_file_mb * MB)
    if (tooBig) return `“${tooBig.name}” is larger than ${limits.max_file_mb} MB.`
    if (files.reduce((n, f) => n + f.size, 0) > limits.max_total_mb * MB)
      return `The files are larger than ${limits.max_total_mb} MB together.`
    const wrong = files.find((f) => !KINDS.includes(f.name.split('.').pop()?.toLowerCase() ?? ''))
    return wrong ? `“${wrong.name}” isn’t a PNG, JPEG, WebP or PDF.` : null
  }, [files, limits])

  const left = limits.max_answer_chars - answer.length
  const canSend = answer.trim().length > 0 && left >= 0 && !fileProblem && !busy

  async function send(e: React.FormEvent) {
    e.preventDefault()
    if (!canSend) return
    setBusy(true)
    setProblem(null)
    const form = new FormData()
    form.append('answer', answer)
    links.map((l) => l.trim()).filter(Boolean).forEach((l) => form.append('links', l))
    files.forEach((f) => form.append('files', f))
    try {
      onChange(await ratedApi.submit(activity.id, form))
    } catch (err) {
      setProblem(err instanceof ApiError && err.message ? err.message : 'That didn’t send. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className={styles.form} onSubmit={(e) => void send(e)} aria-label={revising ? 'Hand in a revision' : 'Hand in your work'}>
      <h3 className={styles.h}>{revising ? 'Your revision' : 'Your answer'}</h3>
      <label htmlFor={`answer-${activity.id}`} className="sr-only">
        Your answer
      </label>
      <textarea
        id={`answer-${activity.id}`}
        className={`input ${styles.answer}`}
        rows={9}
        value={answer}
        onChange={(e) => {
          setAnswer(e.target.value)
          setProblem(null)
        }}
        placeholder="Write your reply or your findings here."
      />
      <p className={left < 0 ? styles.problem : styles.note}>
        {left < 0 ? `${-left} characters too many` : `${left.toLocaleString()} characters left`}
      </p>

      <fieldset className={styles.group}>
        <legend>Links (optional)</legend>
        {links.map((value, i) => (
          <div key={i} className={styles.linkRow}>
            <input
              className="input"
              type="url"
              inputMode="url"
              aria-label={`Link ${i + 1}`}
              placeholder="https://…"
              value={value}
              onChange={(e) => {
                const value = e.target.value
                setLinks((prev) => prev.map((l, j) => (j === i ? value : l)))
                setProblem(null)
              }}
            />
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setLinks((prev) => prev.filter((_, j) => j !== i))}>
              Remove
            </button>
          </div>
        ))}
        {links.length < limits.max_links && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setLinks((prev) => [...prev, ''])}>
            Add a link
          </button>
        )}
      </fieldset>

      {limits.allowed && (
        <fieldset className={styles.group}>
          <legend>Screenshots or a PDF (optional)</legend>
          <p className={styles.note}>
            PNG, JPEG, WebP or PDF · up to {limits.max_files} files · {limits.max_file_mb} MB each
          </p>
          <input
            ref={picker}
            type="file"
            multiple
            className="sr-only"
            id={`files-${activity.id}`}
            accept=".png,.jpg,.jpeg,.webp,.pdf"
            aria-label="Choose files"
            onChange={(e) => {
              const picked = Array.from(e.target.files ?? [])
              setFiles((prev) => [...prev, ...picked])
              setProblem(null)
              e.target.value = ''
            }}
          />
          <button type="button" className="btn btn-sm" onClick={() => picker.current?.click()}>
            Choose files
          </button>
          {files.length > 0 && (
            <ul className={styles.fileList} aria-label="Files to hand in">
              {files.map((f, i) => (
                <li key={`${f.name}-${i}`}>
                  <span>
                    {f.name} <span className={styles.note}>· {size(f.size)}</span>
                  </span>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => {
                      setFiles((prev) => prev.filter((_, j) => j !== i))
                      setProblem(null)
                    }}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
          {fileProblem && (
            <p className={styles.problem} role="alert">
              {fileProblem}
            </p>
          )}
        </fieldset>
      )}

      {problem && (
        <p className={styles.problem} role="alert">
          {problem}
        </p>
      )}
      <p>
        <button type="submit" className="btn btn-primary" disabled={!canSend}>
          {busy ? 'Handing in…' : revising ? 'Hand in revision' : 'Hand in'}
        </button>
        {config.revision_days > 0 && !revising && (
          <span className={styles.note}> You can revise it from your mentor’s feedback.</span>
        )}
      </p>
    </form>
  )
}

function Revision({ r, open }: { r: RatedRevision; open: boolean }) {
  const rating = r.rating
  const head =
    r.state === 'withdrawn'
      ? 'Withdrawn'
      : r.state === 'submitted'
        ? 'Waiting for a mentor'
        : rating
          ? `${rating.passed ? 'Passed' : 'Changes requested'} · ${score(rating.raw_score)}`
          : 'Rated'
  return (
    <li>
      <details open={open}>
        <summary>
          <strong>Revision {r.revision}</strong> · handed in {when(r.submitted_at)}
          {r.late ? ' (late)' : ''} · {head}
        </summary>
        <div className={styles.body}>
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
                  <span className={styles.note}>· {size(f.size_bytes)}</span>
                </li>
              ))}
            </ul>
          )}
          {rating && (
            <div className={styles.rating}>
              <p>
                <strong>{rating.mentor ?? 'Your mentor'}</strong> rated this {score(rating.raw_score)}
                {rating.rated_at ? ` on ${when(rating.rated_at)}` : ''}.
              </p>
              <table className={styles.scores}>
                <caption className="sr-only">Scores for revision {r.revision}</caption>
                <tbody>
                  {rating.scores.map((s) => (
                    <tr key={s.key}>
                      <th scope="row">{s.label}</th>
                      <td>{`${s.score} / ${s.max}`}</td>
                      <td>{s.feedback}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className={styles.prose}>{rating.comment}</p>
            </div>
          )}
        </div>
      </details>
    </li>
  )
}
