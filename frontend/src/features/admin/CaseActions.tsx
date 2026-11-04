import { useState } from 'react'

import { Dialog } from '../../components/Dialog'
import { ApiError } from '../../lib/api'
import { adminApi, type CaseStatus } from './adminApi'
import styles from './ratings.module.css'

type Action = 'extend' | 'waive' | 'close' | 'reopen'

const COPY: Record<Action, { button: string; title: string; body: string; confirm: string }> = {
  extend: {
    button: 'Extend deadline',
    title: 'Give more time',
    body: 'The learner’s deadline moves later, counted from now (or from the current deadline if that is later). It does not unblock anything by itself.',
    confirm: 'Extend',
  },
  waive: {
    button: 'Waive',
    title: 'Waive this activity',
    body: 'The learner is excused from it. It stops holding their lesson up and is recorded as waived — never as passed. Anything waiting for a mentor is withdrawn.',
    confirm: 'Waive it',
  },
  close: {
    button: 'Close',
    title: 'Close as not passed',
    body: 'Ends this for the learner. It stops holding their lesson up and is recorded as closed, not passed. Anything waiting for a mentor is withdrawn.',
    confirm: 'Close it',
  },
  reopen: {
    button: 'Reopen',
    title: 'Reopen this activity',
    body: 'The learner can hand work in again, with a fresh deadline. If their lesson was finished because of this, it is reopened too.',
    confirm: 'Reopen',
  },
}

interface Props {
  caseId: number
  status: CaseStatus
  /** Called with a short message after something changed, so the screen can reload. */
  onDone: (message: string) => void
}

/** What a trainer or admin can do to one learner's case. Every action needs a reason, which
 * is kept in the audit log. Hidden from people who can't do them: the server enforces too. */
export function CaseActions({ caseId, status, onDone }: Props) {
  const [action, setAction] = useState<Action | null>(null)
  const finished = status === 'passed'
  const closed = status === 'waived' || status === 'not_passed'
  const available: Action[] = finished ? [] : closed ? ['reopen'] : ['extend', 'waive', 'close']
  if (available.length === 0) return null
  return (
    <>
      <span className={styles.actionRow}>
        {available.map((a) => (
          <button key={a} type="button" className="btn btn-sm" onClick={() => setAction(a)}>
            {COPY[a].button}
          </button>
        ))}
      </span>
      {action && (
        <CaseDialog
          caseId={caseId}
          action={action}
          onClose={() => setAction(null)}
          onDone={(message) => {
            setAction(null)
            onDone(message)
          }}
        />
      )}
    </>
  )
}

function CaseDialog({
  caseId,
  action,
  onClose,
  onDone,
}: {
  caseId: number
  action: Action
  onClose: () => void
  onDone: (message: string) => void
}) {
  const copy = COPY[action]
  const [reason, setReason] = useState('')
  const [days, setDays] = useState('3')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      await adminApi.caseAction(caseId, action, {
        reason,
        ...(action === 'extend' ? { days: Number(days) } : {}),
      })
      onDone(`${copy.title}: done.`)
    } catch (err) {
      setProblem(err instanceof ApiError && err.message ? err.message : 'That didn’t work. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      title={copy.title}
      width={520}
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="case-action" className="btn btn-primary" disabled={busy || !reason.trim()}>
            {busy ? 'Working…' : copy.confirm}
          </button>
        </>
      }
    >
      <form id="case-action" className={styles.dialogForm} onSubmit={(e) => void submit(e)}>
        <p className={styles.hint}>{copy.body}</p>
        {action === 'extend' && (
          <div className={styles.field}>
            <label htmlFor="case-days">Days</label>
            <input
              id="case-days"
              className="input"
              type="number"
              min={1}
              value={days}
              onChange={(e) => setDays(e.target.value)}
            />
          </div>
        )}
        <div className={styles.field}>
          <label htmlFor="case-reason">Reason (kept in the audit log)</label>
          <textarea
            id="case-reason"
            className="input"
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
          />
        </div>
        {problem && (
          <p className={styles.problem} role="alert">
            {problem}
          </p>
        )}
      </form>
    </Dialog>
  )
}
