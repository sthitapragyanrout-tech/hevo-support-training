import { useState } from 'react'

import { Dialog } from '../../components/Dialog'
import { adminApi, type EnrollOptions, type EnrollmentRow } from './adminApi'
import styles from './people.module.css'
import page from './enrollment.module.css'

interface Props {
  row: EnrollmentRow
  groups: EnrollOptions['programs']
  onClose: () => void
  onDone: (message: string) => void
}

/** Which group (L1, L2, …) this enrollment counts under on the Dashboard. Only groups that
 * include the course are offered; changing it doesn't change what the learner can open. */
export function GroupDialog({ row, groups, onClose, onDone }: Props) {
  const [group, setGroup] = useState(row.program ? String(row.program.id) : '')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const fitting = groups.filter((g) => g.course_ids.includes(row.course.id))

  async function save() {
    setBusy(true)
    setProblem(null)
    try {
      await adminApi.setGroup(row.id, group ? Number(group) : null)
      const name = fitting.find((g) => String(g.id) === group)?.name
      onDone(
        name
          ? `${row.user.name} is in ${name} for ${row.course.title}.`
          : `${row.user.name} is in no group for ${row.course.title}.`,
      )
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t change the group.')
      setBusy(false)
    }
  }

  return (
    <Dialog
      title={`Group for ${row.user.name}`}
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() => void save()}
          >
            {busy ? 'Saving…' : 'Save'}
          </button>
        </>
      }
    >
      <div className={page.stack}>
        <p className={page.note}>
          On <strong>{row.course.title}</strong>. The group is how results are grouped on the
          Dashboard; it doesn’t change what they can open.
        </p>
        <label className={styles.field}>
          <span>Group</span>
          <select
            className="input"
            aria-label="Group"
            value={group}
            onChange={(e) => setGroup(e.target.value)}
          >
            <option value="">No group</option>
            {fitting.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
        {fitting.length === 0 && (
          <p className={page.note}>
            No group includes this course yet. Add it to one under Groups.
          </p>
        )}
        {problem && (
          <p className={styles.problem} role="alert">
            {problem}
          </p>
        )}
      </div>
    </Dialog>
  )
}
