import { useState } from 'react'

import { DataTable, type Column } from '../../components/DataTable'
import { PageState } from '../../components/PageState'
import { AdminPage, Toolbar } from './AdminPage'
import { adminApi, type EnrollmentRow } from './adminApi'
import { BulkEnrollDialog } from './BulkEnrollDialog'
import { EnrollDialog } from './EnrollDialog'
import { formatWhen } from './format'
import { GroupDialog } from './GroupDialog'
import { MentorDialog } from './MentorDialog'
import { ModulesDialog } from './ModulesDialog'
import { MoveDialog } from './MoveDialog'
import { WithdrawDialog } from './WithdrawDialog'
import { useDebounced, useQuery } from './useQuery'
import styles from './people.module.css'
import page from './enrollment.module.css'

type Open =
  | { kind: 'enroll' }
  | { kind: 'bulk' }
  | { kind: 'mentor' | 'group' | 'modules' | 'withdraw' | 'move'; row: EnrollmentRow }
  | null

export function EnrollmentsPage() {
  const [search, setSearch] = useState('')
  const [course, setCourse] = useState('')
  const [program, setProgram] = useState('')
  const [state, setState] = useState('active')
  const [older, setOlder] = useState(false)
  const [pageNo, setPageNo] = useState(1)
  const [open, setOpen] = useState<Open>(null)
  const [message, setMessage] = useState<string | null>(null)
  const term = useDebounced(search)

  const options = useQuery(() => adminApi.enrollOptions(), 'enroll-options')
  const query = {
    search: term,
    course,
    program,
    state,
    older: older ? 1 : undefined,
    page: pageNo,
  }
  const rows = useQuery(() => adminApi.enrollments(query), JSON.stringify(query))

  function done(text: string) {
    setOpen(null)
    setMessage(text)
    rows.reload()
  }

  async function reenroll(row: EnrollmentRow) {
    try {
      await adminApi.reenroll(row.id)
      done(`${row.user.name} is enrolled again.`)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'We couldn’t do that.')
    }
  }

  const columns: Column<EnrollmentRow>[] = [
    {
      key: 'user',
      header: 'Learner',
      render: (e) => (
        <span className={styles.person}>
          <strong>{e.user.name}</strong>
          {e.user.name !== e.user.email && <span className={styles.sub}>{e.user.email}</span>}
          <span className={styles.sub}>Enrolled {formatWhen(e.enrolled_at)}</span>
        </span>
      ),
    },
    {
      key: 'course',
      header: 'Course',
      render: (e) => (
        <span className={styles.person}>
          <strong>{e.course.title}</strong>
          <span className={styles.sub}>
            Version {e.version.number}
            {e.version.older && (
              <span className={page.older}> · newest is {e.version.latest_number}</span>
            )}
            {e.course.archived && ' · course archived'}
          </span>
          {e.modules.enabled < e.modules.total && (
            <span className={styles.sub}>
              {e.modules.enabled} of {e.modules.total} modules
            </span>
          )}
          {e.program && <span className={styles.sub}>Group: {e.program.name}</span>}
        </span>
      ),
    },
    {
      key: 'mentor',
      header: 'Mentor',
      render: (e) =>
        e.state === 'active' ? (
          (e.mentor?.name ?? 'Shared pool')
        ) : (
          <span className={styles.person}>
            <span>Withdrawn {formatWhen(e.withdrawn_at)}</span>
            {e.withdrawn_reason && <span className={styles.sub}>{e.withdrawn_reason}</span>}
          </span>
        ),
    },
    {
      key: 'actions',
      header: '',
      align: 'end',
      render: (e) => (
        <span className={page.rowActions}>
          {e.state === 'active' ? (
            <>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setOpen({ kind: 'mentor', row: e })}
              >
                Mentor
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setOpen({ kind: 'group', row: e })}
              >
                Group
              </button>
              {e.modules.total > 1 && (
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => setOpen({ kind: 'modules', row: e })}
                >
                  Modules
                </button>
              )}
              {e.version.older && (
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => setOpen({ kind: 'move', row: e })}
                >
                  Move to newest
                </button>
              )}
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setOpen({ kind: 'withdraw', row: e })}
              >
                Withdraw
              </button>
            </>
          ) : (
            <button type="button" className="btn btn-sm" onClick={() => void reenroll(e)}>
              Enroll again
            </button>
          )}
        </span>
      ),
    },
  ]

  return (
    <AdminPage
      eyebrow="People"
      title="Enrollments"
      hint="Who is on which course, which version they are on, and who mentors them. Learners see only the courses they are enrolled on."
      actions={
        <span className={page.actions}>
          <button type="button" className="btn" onClick={() => setOpen({ kind: 'bulk' })}>
            Enroll from a list
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setOpen({ kind: 'enroll' })}
          >
            Enroll people
          </button>
        </span>
      }
    >
      {message && (
        <p className={page.saved} role="status">
          {message}
        </p>
      )}
      <Toolbar>
        <input
          type="search"
          className="input"
          placeholder="Search by name, email or employee id"
          aria-label="Search enrollments"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPageNo(1)
          }}
        />
        <select
          className="input"
          aria-label="Course"
          value={course}
          onChange={(e) => {
            setCourse(e.target.value)
            setPageNo(1)
          }}
        >
          <option value="">All courses</option>
          {options.data?.courses.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
        <select
          className="input"
          aria-label="Group"
          value={program}
          onChange={(e) => {
            setProgram(e.target.value)
            setPageNo(1)
          }}
        >
          <option value="">Any group</option>
          {options.data?.programs.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          className="input"
          aria-label="Status"
          value={state}
          onChange={(e) => {
            setState(e.target.value)
            setPageNo(1)
          }}
        >
          <option value="active">Active</option>
          <option value="withdrawn">Withdrawn</option>
          <option value="all">All</option>
        </select>
        <label className={styles.inline}>
          <input
            type="checkbox"
            checked={older}
            onChange={(e) => {
              setOlder(e.target.checked)
              setPageNo(1)
            }}
          />
          On an older version
        </label>
      </Toolbar>

      {rows.loading ? (
        <PageState kind="loading" />
      ) : rows.error || !rows.data ? (
        <PageState kind="error" title="Couldn’t load enrollments" onRetry={rows.reload}>
          {rows.error}
        </PageState>
      ) : (
        <DataTable
          label="Enrollments"
          columns={columns}
          rows={rows.data.results}
          rowKey={(e) => e.id}
          meta={rows.data}
          onPage={setPageNo}
          busy={rows.refreshing}
          empty={
            term || course || program || older || state !== 'active'
              ? 'No enrollments match.'
              : 'No one is enrolled yet. Use “Enroll people” to put learners on a course.'
          }
        />
      )}

      {open?.kind === 'enroll' && options.data && (
        <EnrollDialog options={options.data} onClose={() => setOpen(null)} onDone={done} />
      )}
      {open?.kind === 'bulk' && options.data && (
        <BulkEnrollDialog options={options.data} onClose={() => setOpen(null)} onDone={done} />
      )}
      {open?.kind === 'mentor' && options.data && (
        <MentorDialog
          row={open.row}
          mentors={options.data.mentors}
          onClose={() => setOpen(null)}
          onDone={done}
        />
      )}
      {open?.kind === 'group' && options.data && (
        <GroupDialog
          row={open.row}
          groups={options.data.programs}
          onClose={() => setOpen(null)}
          onDone={done}
        />
      )}
      {open?.kind === 'modules' && (
        <ModulesDialog row={open.row} onClose={() => setOpen(null)} onDone={done} />
      )}
      {open?.kind === 'withdraw' && (
        <WithdrawDialog row={open.row} onClose={() => setOpen(null)} onDone={done} />
      )}
      {open?.kind === 'move' && (
        <MoveDialog row={open.row} onClose={() => setOpen(null)} onDone={done} />
      )}
    </AdminPage>
  )
}
