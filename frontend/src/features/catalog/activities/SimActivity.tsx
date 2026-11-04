import { useState } from 'react'

import { Icon } from '../../../components/Icon'
import { ApiError, simApi, type SimSession } from '../../../lib/api'
import { useCourse } from '../courseContext'
import { ActivityShell } from './ActivityShell'
import { outOf5 } from './simFormat'
import styles from './SimActivity.module.css'
import { TicketWindow } from './TicketWindow'
import type { RendererProps } from './types'

/** Practice answering an AI customer in a ticket-style window. It's practice, not a
 * test: finishing enough scored tickets (five by default) completes the activity,
 * whatever each one scored. A question can be skipped before replying. */
export function SimActivity({ activity }: RendererProps) {
  const { progress, preview } = useCourse()
  const config = activity.config
  const max = typeof config.max_exchanges === 'number' ? config.max_exchanges : 6
  const required = typeof config.required_tickets === 'number' ? config.required_tickets : 5
  const skipsAllowed = typeof config.skips_allowed === 'number' ? config.skips_allowed : 5

  const state = progress.activities[activity.id]
  const complete = state === 'completed'
  const exhausted = state === 'exhausted'
  const summary = progress.attempts[activity.id]
  const sim = progress.sim[activity.id]
  const live = sim?.live ?? null
  const lastFinished = sim?.last_finished ?? null
  const done = summary?.count ?? 0
  const average = sim?.average != null ? sim.average * 5 : null
  const skipsLeft = Math.max(skipsAllowed - (sim?.skips_used ?? 0), 0)
  const triesLeft: number | null = summary
    ? summary.attempts_left
    : activity.max_attempts > 0
      ? activity.max_attempts
      : null
  const canTryAgain = !complete && !exhausted && triesLeft !== 0

  const [window_, setWindow] = useState<SimSession | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const canRecord = progress.available && !preview

  const avgNote = average === null ? '' : ` · average ${outOf5(average)}`
  const meta = [
    'Practice tickets',
    complete
      ? `Done · ${done} finished${avgNote}`
      : exhausted
        ? `All tickets used · ${done} of ${required} finished${avgNote}`
        : done > 0
          ? `${done} of ${required} done${avgNote}`
          : `finish ${required} tickets · up to ${max} replies each`,
    activity.is_required ? 'Required' : 'Optional',
  ].join(' · ')

  async function open(task: () => Promise<SimSession>) {
    setBusy(true)
    setProblem(null)
    try {
      setWindow(await task())
    } catch (err) {
      setProblem(err instanceof ApiError && err.message ? err.message : 'We couldn’t open the ticket. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const view = () => open(() => simApi.get((live?.id ?? lastFinished) as number))
  const start = () => open(() => (preview ? simApi.preview(activity.id) : simApi.start(activity.id)))

  let label = done > 0 ? 'Start next ticket' : 'Start practice'
  let action = start
  if (preview) label = 'Try it (not scored)'
  else if (live) {
    label = 'Continue'
    action = view
  } else if ((complete || exhausted) && lastFinished) {
    label = 'View last result'
    action = view
  }

  return (
    <ActivityShell
      icon="chat"
      title={activity.title}
      meta={meta}
      done={complete}
      muted={exhausted}
      panel={
        problem ? (
          <p className={styles.problem} role="alert">
            {problem}
          </p>
        ) : undefined
      }
    >
      <button
        type="button"
        className={`btn btn-sm ${complete || exhausted ? '' : 'btn-primary'}`}
        disabled={busy || (!preview && !canRecord)}
        onClick={() => void action()}
      >
        {label === 'Start practice' || label === 'Continue' || label === 'Start next ticket' ? (
          <Icon name="chat" size={14} />
        ) : null}{' '}
        {label}
      </button>
      {!live && !complete && !exhausted && lastFinished && !preview && (
        <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void view()}>
          Last result
        </button>
      )}
      {window_ && (
        <TicketWindow
          key={window_.id} // a different ticket is a fresh window, not the old one with new props
          initial={window_}
          canTryAgain={!window_.preview && canTryAgain}
          skipsLeft={preview ? 0 : skipsLeft}
          onTryAgain={() => void start()}
          onSettled={() => void progress.refresh()}
          onClose={() => {
            setWindow(null)
            if (!window_.preview) void progress.refresh()
          }}
        />
      )}
    </ActivityShell>
  )
}
