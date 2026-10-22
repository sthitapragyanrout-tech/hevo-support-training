import { useBuilder } from './builderContext'
import styles from './SettingsTab.module.css'

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

export function SettingsTab() {
  const { course } = useBuilder()
  const { version, published_version: published } = course

  return (
    <div className={styles.page}>
      <h2>Course status</h2>
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
