import { useState } from 'react'

import { Icon } from '../../../components/Icon'
import { ApiError, ratedApi, type RatedView } from '../../../lib/api'
import { useCourse } from '../courseContext'
import { ActivityShell } from './ActivityShell'
import styles from './ManualSimActivity.module.css'
import { ManualSimPanel } from './ManualSimPanel'
import { statusLine } from './manualSimFormat'
import type { RendererProps } from './types'

/** A realistic task a mentor rates against a rubric. The learner hands work in, reads the
 * feedback, and revises until it passes. The row says where things stand; the work itself
 * opens in place beneath it. */
export function ManualSimActivity({ activity }: RendererProps) {
  const { progress, preview } = useCourse()
  const state = progress.activities[activity.id]
  const done = state === 'completed'
  const closed = state === 'exhausted'
  const rated = progress.rated[activity.id]
  const [view, setView] = useState<RatedView | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const canRecord = progress.available && !preview

  const { line } = statusLine(rated, 'Rated by a mentor against a rubric')
  const meta = ['Simulation', preview ? 'Preview — nothing is recorded' : line, activity.is_required ? 'Required' : 'Optional'].join(' · ')

  async function toggle() {
    if (open) {
      setOpen(false)
      return
    }
    setProblem(null)
    if (preview) {
      setOpen(true)
      return
    }
    setBusy(true)
    try {
      // Opening it is what starts the learner's deadline (once).
      setView(await ratedApi.open(activity.id))
      await progress.refresh()
      setOpen(true)
    } catch (err) {
      setProblem(err instanceof ApiError && err.message ? err.message : 'We couldn’t open this. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const label = open
    ? 'Close'
    : done || closed
      ? 'View'
      : rated?.status === 'changes_requested'
        ? 'Revise'
        : rated?.status === 'waiting'
          ? 'View'
          : 'Open'

  return (
    <ActivityShell
      icon="chat"
      title={activity.title}
      meta={meta}
      done={done}
      muted={closed}
      panel={
        <>
          {problem && (
            <p className={styles.problem} role="alert">
              {problem}
            </p>
          )}
          {open && (
            <ManualSimPanel
              activity={activity}
              view={view}
              preview={preview}
              onChange={(next) => {
                setView(next)
                void progress.refresh()
              }}
            />
          )}
        </>
      }
    >
      <button
        type="button"
        className={`btn btn-sm ${done || closed || open ? '' : 'btn-primary'}`}
        disabled={busy || (!preview && !canRecord)}
        aria-expanded={open}
        onClick={() => void toggle()}
      >
        {!open && label === 'Open' ? <Icon name="chat" size={14} /> : null} {label}
      </button>
    </ActivityShell>
  )
}
