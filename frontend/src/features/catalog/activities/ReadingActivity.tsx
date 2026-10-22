import { useState } from 'react'

import { Icon } from '../../../components/Icon'
import { useCourse } from '../courseContext'
import { ActivityShell } from './ActivityShell'
import styles from './ReadingActivity.module.css'
import type { RendererProps } from './types'

/** Open the reading, then say you've read it. Self-attested on purpose —
 * a reading has nothing to measure; the confirmation is the record. */
export function ReadingActivity({ activity }: RendererProps) {
  const { progress, preview } = useCourse()
  const [busy, setBusy] = useState(false)
  const state = progress.activities[activity.id]
  const done = state === 'completed'
  const url = typeof activity.config.source_url === 'string' ? activity.config.source_url : ''
  const minutes =
    typeof activity.config.estimated_read_minutes === 'number'
      ? activity.config.estimated_read_minutes
      : null

  const meta = [
    minutes ? `Reading · about ${minutes} min` : 'Reading',
    activity.is_required ? 'Required' : 'Optional',
  ].join(' · ')

  async function run(task: () => Promise<void>) {
    setBusy(true)
    try {
      await task()
    } finally {
      setBusy(false)
    }
  }

  // In an author's preview nothing is recorded, so only the link is live.
  const canRecord = progress.available && !preview

  return (
    <ActivityShell icon="book" title={activity.title} meta={meta} done={done}>
      {done ? (
        <>
          <span className={styles.read}>Read</span>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={busy || !canRecord}
            onClick={() => void run(() => progress.uncompleteActivity(activity.id))}
          >
            Mark as unread
          </button>
        </>
      ) : (
        <>
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-sm"
              onClick={() => canRecord && void progress.startActivity(activity.id)}
            >
              Open reading <Icon name="external" size={14} />
            </a>
          )}
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={busy || !canRecord}
            title={preview ? 'Progress isn’t recorded in preview' : undefined}
            onClick={() => void run(() => progress.completeActivity(activity.id))}
          >
            I’ve read this
          </button>
        </>
      )}
    </ActivityShell>
  )
}
