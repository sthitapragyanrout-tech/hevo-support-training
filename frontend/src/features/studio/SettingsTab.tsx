import { useState } from 'react'

import { studioApi } from './studioApi'
import { useBuilder } from './builderContext'
import styles from './SettingsTab.module.css'

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

const ORDERS = [
  {
    value: 'free',
    label: 'Learners can open any lesson',
    hint: 'Everything is available from the start. Good for reference material.',
  },
  {
    value: 'sequential',
    label: 'Learners go in order',
    hint: 'Each lesson unlocks when the required lessons before it are complete. A quiz counts once it’s passed or its attempts are used up. Optional lessons never hold anyone up.',
  },
] as const

export function SettingsTab() {
  const { course, apply } = useBuilder()
  const { version, published_version: published } = course
  const order = course.learning_order ?? 'free'
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  async function choose(value: 'free' | 'sequential') {
    if (value === order) return
    setBusy(true)
    setProblem(null)
    try {
      apply(await studioApi.updateOverview(course.id, { learning_order: value }))
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t save that.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.page}>
      <h2>How learners move through the course</h2>
      <fieldset className={styles.options} disabled={!course.editable || busy}>
        <legend className="sr-only">Learning order</legend>
        {ORDERS.map((o) => (
          <label key={o.value} className={styles.option}>
            <input
              type="radio"
              name="learning-order"
              checked={order === o.value}
              onChange={() => void choose(o.value)}
            />
            <span>
              <strong>{o.label}</strong>
              <span className={styles.hint}>{o.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {!course.editable && (
        <p className={styles.note}>This can be changed while the course is a draft.</p>
      )}
      {problem && (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      )}

      <h2 className={styles.next}>Course status</h2>
      <dl className={styles.facts}>
        <div>
          <dt>Status</dt>
          <dd>{course.status.label}</dd>
        </div>
        {version && version.state !== 'published' && (
          <div>
            <dt>Working copy</dt>
            <dd>Version {version.number}</dd>
          </div>
        )}
        {published && (
          <>
            <div>
              <dt>Live for learners</dt>
              <dd>
                Version {published.number}, published {when(published.published_at)}
              </dd>
            </div>
          </>
        )}
        {version?.submitted_at && (
          <div>
            <dt>Submitted for publishing</dt>
            <dd>
              {when(version.submitted_at)}
              {version.submitted_by && ` by ${version.submitted_by}`}
            </dd>
          </div>
        )}
      </dl>
      <p className={styles.note}>
        Publishing never changes what learners already in progress are seeing — they stay on the
        version they started. Anyone starting later sees the newest published version.
      </p>
    </div>
  )
}
