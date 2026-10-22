import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Dialog } from '../../components/Dialog'
import { studioApi } from './studioApi'
import type { AuthCourse, ChecklistResult } from './types'
import styles from './PublishPanel.module.css'

type Mode = 'submit' | 'publish'

interface Props {
  course: AuthCourse
  apply: (course: AuthCourse) => void
}

/** The one place a course's state changes: Edit → Submit → Publish → Return.
 * Which buttons appear comes from `course.actions` (computed by the server
 * with `can()`), never from guessing the user's role. */
export function PublishPanel({ course, apply }: Props) {
  const navigate = useNavigate()
  const [dialog, setDialog] = useState<{ mode: Mode; checklist: ChecklistResult | null } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { actions } = course

  async function run(task: () => Promise<AuthCourse>, after?: () => void) {
    setBusy(true)
    setError(null)
    try {
      apply(await task())
      after?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  async function open(mode: Mode) {
    setError(null)
    setDialog({ mode, checklist: null })
    try {
      setDialog({ mode, checklist: await studioApi.checklist(course.id) })
    } catch (err) {
      setDialog(null)
      setError(err instanceof Error ? err.message : 'Couldn’t check the course.')
    }
  }

  async function confirm() {
    if (!dialog) return
    const task = dialog.mode === 'publish' ? studioApi.publish : studioApi.submit
    await run(() => task(course.id), () => setDialog(null))
  }

  const inReview = course.status.key === 'in_review'
  const publishing = dialog?.mode === 'publish'

  return (
    <div className={styles.panel}>
      {actions.start_draft && (
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy}
          onClick={() =>
            void run(
              () => studioApi.startDraft(course.id),
              () => navigate(`/studio/courses/${course.id}/curriculum`),
            )
          }
        >
          Edit course
        </button>
      )}

      {inReview && actions.return_to_draft && (
        <button
          type="button"
          className="btn"
          disabled={busy}
          onClick={() => void run(() => studioApi.returnToDraft(course.id))}
        >
          Return to draft
        </button>
      )}
      {actions.publish && (
        <button type="button" className="btn btn-primary" onClick={() => void open('publish')}>
          Publish
        </button>
      )}
      {actions.submit && !actions.publish && (
        <button type="button" className="btn btn-primary" onClick={() => void open('submit')}>
          Submit for publish
        </button>
      )}
      {inReview && !actions.publish && (
        <span className={styles.note}>Waiting for an administrator to publish.</span>
      )}

      {error && (
        <span role="alert" className={styles.error}>
          {error}
        </span>
      )}

      {dialog && (
        <Dialog
          title={publishing ? 'Publish this course?' : 'Submit for publishing?'}
          width={520}
          onClose={() => setDialog(null)}
          actions={
            <>
              <button type="button" className="btn" onClick={() => setDialog(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy || !dialog.checklist?.ok}
                onClick={() => void confirm()}
              >
                {busy ? 'Working…' : publishing ? 'Publish' : 'Submit'}
              </button>
            </>
          }
        >
          {!dialog.checklist ? (
            <p className={styles.muted}>Checking the course…</p>
          ) : dialog.checklist.ok ? (
            <p>
              {publishing
                ? 'Learners will see this version straight away. Anyone already on an earlier version keeps it.'
                : 'The course will be locked while an administrator reviews it. They can send it back to you.'}
            </p>
          ) : (
            <>
              <p>Fix these first:</p>
              <ul className={styles.issues}>
                {dialog.checklist.issues.map((issue, i) => (
                  <li key={i}>
                    {issue.node_id ? (
                      <Link
                        to={`/studio/courses/${course.id}/curriculum/${issue.node_id}`}
                        onClick={() => setDialog(null)}
                      >
                        {issue.message}
                      </Link>
                    ) : (
                      issue.message
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Dialog>
      )}
    </div>
  )
}
