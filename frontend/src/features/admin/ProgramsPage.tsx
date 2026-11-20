import { useState } from 'react'

import { DataTable, type Column } from '../../components/DataTable'
import { PageState } from '../../components/PageState'
import { AdminPage } from './AdminPage'
import { adminApi, type ProgramRow } from './adminApi'
import { formatWhen } from './format'
import { ProgramDialog } from './ProgramDialog'
import { useQuery } from './useQuery'
import styles from './people.module.css'
import page from './enrollment.module.css'

export function ProgramsPage() {
  const [archived, setArchived] = useState(false)
  const [editing, setEditing] = useState<ProgramRow | 'new' | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const programs = useQuery(() => adminApi.programs(archived), `programs:${archived}`)
  const options = useQuery(() => adminApi.enrollOptions(), 'enroll-options')

  async function run(work: () => Promise<string>) {
    try {
      setMessage(await work())
      programs.reload()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'We couldn’t do that.')
    }
  }

  const columns: Column<ProgramRow>[] = [
    {
      key: 'name',
      header: 'Group',
      render: (p) => (
        <span className={styles.person}>
          <strong>{p.name}</strong>
          {p.description && <span className={styles.sub}>{p.description}</span>}
        </span>
      ),
    },
    {
      key: 'courses',
      header: 'Courses',
      render: (p) =>
        p.courses.length === 0 ? (
          '—'
        ) : (
          <span className={styles.person}>
            {p.courses.map((c) => (
              <span key={c.course_id}>
                {c.title}
                {!c.required && <span className={styles.sub}> · optional</span>}
                {!c.published && <span className={styles.sub}> · not published</span>}
              </span>
            ))}
          </span>
        ),
    },
    {
      key: 'dates',
      header: 'Dates',
      hideOnMobile: true,
      render: (p) =>
        p.starts_on || p.ends_on ? `${formatWhen(p.starts_on)} – ${formatWhen(p.ends_on)}` : '—',
    },
    { key: 'members', header: 'People', align: 'end', render: (p) => p.members },
    {
      key: 'actions',
      header: '',
      align: 'end',
      render: (p) => (
        <span className={page.rowActions}>
          {p.archived ? (
            <button
              type="button"
              className="btn btn-sm"
              onClick={() =>
                void run(async () => (await adminApi.restoreProgram(p.id), `${p.name} is back.`))
              }
            >
              Restore
            </button>
          ) : (
            <>
              <button type="button" className="btn btn-sm" onClick={() => setEditing(p)}>
                Edit
              </button>
              {p.members > 0 && (
                <button
                  type="button"
                  className="btn btn-sm"
                  title="Enroll its people on any course added since"
                  onClick={() =>
                    void run(async () => {
                      const r = await adminApi.enrollMissing(p.id)
                      return r.enrolled > 0
                        ? `Enrolled ${plural(r.enrolled, 'new enrollment')} for ${plural(r.people, 'person', 'people')}.`
                        : `Everyone in ${p.name} is already up to date.`
                    })
                  }
                >
                  Enroll missing
                </button>
              )}
              <button
                type="button"
                className="btn btn-sm"
                onClick={() =>
                  void run(
                    async () => (await adminApi.archiveProgram(p.id), `${p.name} is archived.`),
                  )
                }
              >
                Archive
              </button>
            </>
          )}
        </span>
      ),
    },
  ]

  return (
    <AdminPage
      eyebrow="People"
      title="Groups"
      hint="A group (such as L1 or L2) is a named, ordered set of courses: enroll a whole group in one step, and see results by group on the Dashboard."
      actions={
        <button type="button" className="btn btn-primary" onClick={() => setEditing('new')}>
          New group
        </button>
      }
    >
      {message && (
        <p className={page.saved} role="status">
          {message}
        </p>
      )}
      <label className={styles.inline} style={{ marginBottom: 'var(--sp-3)' }}>
        <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} />
        Show archived groups
      </label>
      {programs.loading ? (
        <PageState kind="loading" />
      ) : programs.error || !programs.data ? (
        <PageState kind="error" title="Couldn’t load groups" onRetry={programs.reload}>
          {programs.error}
        </PageState>
      ) : (
        <DataTable
          label="Groups"
          columns={columns}
          rows={programs.data.results}
          rowKey={(p) => p.id}
          busy={programs.refreshing}
          empty={
            archived
              ? 'No archived groups.'
              : 'No groups yet. Create one (for example L1) to enroll people together.'
          }
        />
      )}
      {editing && options.data && (
        <ProgramDialog
          program={editing === 'new' ? null : editing}
          courses={options.data.courses}
          onClose={() => setEditing(null)}
          onSaved={(text) => {
            setEditing(null)
            setMessage(text)
            programs.reload()
          }}
        />
      )}
    </AdminPage>
  )
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`
