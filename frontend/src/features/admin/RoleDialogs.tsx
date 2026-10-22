import { useState } from 'react'

import { Dialog } from '../../components/Dialog'
import { adminApi, type ActionInfo, type RoleRow } from './adminApi'
import styles from './people.module.css'

/** Add a role and, optionally, tick what it may do straight away. */
export function AddRoleDialog({
  actions,
  onClose,
  onCreated,
}: {
  actions: ActionInfo[]
  onClose: () => void
  onCreated: (role: RoleRow) => void
}) {
  const [name, setName] = useState('')
  const [chosen, setChosen] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      onCreated(await adminApi.createRole(name, chosen))
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t add that role.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      title="Add a role"
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            form="add-role"
            className="btn btn-primary"
            disabled={busy || !name.trim()}
          >
            {busy ? 'Adding…' : 'Add role'}
          </button>
        </>
      }
    >
      <form id="add-role" className={styles.form} onSubmit={(e) => void submit(e)}>
        <label className={styles.field}>
          <span>Role name</span>
          <input
            className="input"
            value={name}
            maxLength={64}
            placeholder="e.g. Senior support"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <fieldset className={styles.checksCol}>
          <legend className={styles.legend}>What can this role do?</legend>
          {actions.map((a) => (
            <label key={a.key}>
              <input
                type="checkbox"
                checked={chosen.includes(a.key)}
                onChange={(e) =>
                  setChosen(e.target.checked ? [...chosen, a.key] : chosen.filter((k) => k !== a.key))
                }
              />
              <span>
                {a.label}
                <span className={styles.sub}> — {a.description}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <p className={styles.sub}>You can change this any time from the grid. Adding a role is recorded in the audit log.</p>
        {problem && (
          <p role="alert" className={styles.problem}>
            {problem}
          </p>
        )}
      </form>
    </Dialog>
  )
}

export function RenameRoleDialog({
  role,
  onClose,
  onRenamed,
}: {
  role: RoleRow
  onClose: () => void
  onRenamed: () => void
}) {
  const [name, setName] = useState(role.label)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      await adminApi.renameRole(role.id, name)
      onRenamed()
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t rename that role.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      title="Rename role"
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            form="rename-role"
            className="btn btn-primary"
            disabled={busy || !name.trim() || name.trim() === role.label}
          >
            {busy ? 'Saving…' : 'Rename'}
          </button>
        </>
      }
    >
      <form id="rename-role" className={styles.form} onSubmit={(e) => void submit(e)}>
        <label className={styles.field}>
          <span>Role name</span>
          <input
            className="input"
            value={name}
            maxLength={64}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        {problem && (
          <p role="alert" className={styles.problem}>
            {problem}
          </p>
        )}
      </form>
    </Dialog>
  )
}
