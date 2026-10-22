import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { DataTable, type Column } from '../../components/DataTable'
import { PageState } from '../../components/PageState'
import { useCan } from '../../lib/capabilities'
import { CAN } from '../../lib/capabilityKeys'
import { ConfirmDialog } from '../studio/ConfirmDialog'
import { AdminPage } from './AdminPage'
import { adminApi, type CourseDetail, type VersionRow } from './adminApi'
import { formatDateTime } from './format'
import { useQuery } from './useQuery'
import styles from './people.module.css'

function columns(): Column<VersionRow>[] {
  return [
    {
      key: 'version',
      header: 'Version',
      render: (v) => (
        <span className={styles.person}>
          <strong>v{v.number}</strong>
          <span className={styles.sub}>{v.title ?? ''}</span>
        </span>
      ),
    },
    { key: 'state', header: 'State', render: (v) => v.state_label },
    {
      key: 'content',
      header: 'Content',
      hideOnMobile: true,
      render: (v) => `${v.lessons} lessons · ${v.activities} activities`,
    },
    { key: 'learners', header: 'Learners', align: 'end', render: (v) => v.learners },
    {
      key: 'history',
      header: 'History',
      hideOnMobile: true,
      render: (v) => (
        <span className={styles.person}>
          {v.published_at && (
            <span>
              Published {formatDateTime(v.published_at)}
              {v.published_by ? ` by ${v.published_by}` : ''}
            </span>
          )}
          {v.submitted_at && (
            <span className={styles.sub}>
              Submitted {formatDateTime(v.submitted_at)}
              {v.submitted_by ? ` by ${v.submitted_by}` : ''}
            </span>
          )}
          {!v.published_at && !v.submitted_at && <span className={styles.sub}>—</span>}
        </span>
      ),
    },
  ]
}

export function CourseDetailPage() {
  const { courseId = '' } = useParams()
  const canAuthor = useCan(CAN.authorContent)
  const { data, loading, error, errorStatus, reload } = useQuery(
    () => adminApi.course(courseId),
    `course-${courseId}`,
  )
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  if (loading) return <PageState kind="loading" />
  if (errorStatus === 404) return <PageState kind="empty" title="Course not found" />
  if (error || !data) {
    return (
      <PageState kind="error" title="Couldn’t load this course" onRetry={reload}>
        {error}
      </PageState>
    )
  }

  const archived = data.status.key === 'archived'

  async function toggle(course: CourseDetail) {
    setBusy(true)
    setProblem(null)
    setMessage(null)
    try {
      if (archived) await adminApi.restoreCourse(course.id)
      else await adminApi.archiveCourse(course.id)
      setMessage(archived ? 'Restored. Learners can see it again.' : 'Archived. Learners can no longer see it.')
      reload()
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'That didn’t work. Please try again.')
    } finally {
      setBusy(false)
      setConfirming(false)
    }
  }

  return (
    <AdminPage
      eyebrow="Content · Courses"
      title={data.title}
      hint={
        <>
          {data.slug} · <span className={archived ? styles.state_deactivated : styles.state_active}>{data.status.label}</span>
        </>
      }
      actions={
        <>
          {canAuthor && !archived && (
            <Link to={`/studio/courses/${data.id}`} className="btn">
              Open in Studio
            </Link>
          )}
          <Link to="/admin/courses" className="btn">
            All courses
          </Link>
        </>
      }
    >
      {message && (
        <p role="status" className={styles.saved}>
          {message}
        </p>
      )}
      {problem && (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      )}

      <section className={styles.section} aria-labelledby="versions">
        <h2 id="versions">Versions</h2>
        <p className={styles.sub}>
          Each published version is kept, so learners’ history always has something to point at.
        </p>
        <DataTable
          label="Versions"
          columns={columns()}
          rows={data.versions_history}
          rowKey={(v) => v.id}
          empty="No versions."
        />
      </section>

      {data.can_archive && (
        <section className={styles.section} aria-labelledby="availability">
          <h2 id="availability">Availability</h2>
          <ul className={styles.rows}>
            <li>
              <div>
                <strong>{archived ? 'Archived' : 'Available'}</strong>
                <p className={styles.sub}>
                  {archived
                    ? 'Hidden from learners and from Studio’s list. Progress and scores are kept.'
                    : 'Archiving hides it from learners and from Studio’s list. Nothing is deleted, and you can restore it.'}
                </p>
              </div>
              <button type="button" className="btn" disabled={busy} onClick={() => setConfirming(true)}>
                {archived ? 'Restore' : 'Archive'}
              </button>
            </li>
          </ul>
        </section>
      )}

      {confirming && (
        <ConfirmDialog
          title={archived ? `Restore ${data.title}?` : `Archive ${data.title}?`}
          confirmLabel={archived ? 'Restore' : 'Archive'}
          busy={busy}
          onCancel={() => setConfirming(false)}
          onConfirm={() => void toggle(data)}
        >
          {archived
            ? 'Learners will see it again and can carry on where they left off. This is recorded in the audit log.'
            : 'Learners will no longer see it or be able to record progress. Their existing progress and scores are kept. This is recorded in the audit log.'}
        </ConfirmDialog>
      )}
    </AdminPage>
  )
}
