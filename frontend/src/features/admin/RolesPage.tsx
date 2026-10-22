import { useState } from 'react'
import { Link } from 'react-router-dom'

import { PageState } from '../../components/PageState'
import { ConfirmDialog } from '../studio/ConfirmDialog'
import { AdminPage } from './AdminPage'
import { adminApi, type RoleRow } from './adminApi'
import { AddRoleDialog, RenameRoleDialog } from './RoleDialogs'
import { useQuery } from './useQuery'
import styles from './people.module.css'

/** Who may do what, as a grid: one row per action, one column per role. A
 * tick saves straight away; the server refuses anything that would leave
 * nobody able to fix a mistake. */
export function RolesPage() {
  const { data, loading, error, reload } = useQuery(() => adminApi.roles(), 'roles')
  const [overrides, setOverrides] = useState<Record<number, string[]>>({})
  const [saving, setSaving] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [renaming, setRenaming] = useState<RoleRow | null>(null)
  const [deleting, setDeleting] = useState<RoleRow | null>(null)
  const [busy, setBusy] = useState(false)

  if (loading) return <PageState kind="loading" />
  if (error || !data) {
    return (
      <PageState kind="error" title="Couldn’t load roles" onRetry={reload}>
        {error}
      </PageState>
    )
  }

  const granted = (role: RoleRow) => overrides[role.id] ?? role.permissions

  async function toggle(role: RoleRow, key: string, on: boolean) {
    const current = granted(role)
    const next = on ? [...current, key] : current.filter((k) => k !== key)
    setSaving(`${role.id}-${key}`)
    setProblem(null)
    setMessage(null)
    try {
      const updated = await adminApi.setRolePermissions(role.id, next)
      setOverrides((o) => ({ ...o, [role.id]: updated.permissions }))
      setMessage(`${role.label} can ${on ? 'now' : 'no longer'} ${actionLabel(key)}.`)
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t save that change.')
    } finally {
      setSaving(null)
    }
  }

  const actionLabel = (key: string) =>
    (data?.actions.find((a) => a.key === key)?.label ?? key).toLowerCase()

  return (
    <AdminPage
      eyebrow="People"
      title="Roles"
      hint="What each role may do. People get their abilities only from their roles."
      actions={
        <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
          Add role
        </button>
      }
    >
      {problem && (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      )}
      {message && (
        <p role="status" className={styles.saved}>
          {message}
        </p>
      )}

      <div className={styles.matrixWrap}>
        <table className={styles.matrix}>
          <caption className="sr-only">Which role may do what</caption>
          <thead>
            <tr>
              <th scope="col">Can…</th>
              {data.roles.map((role) => (
                <th key={role.id} scope="col">
                  <span>{role.label}</span>
                  <Link to={`/admin/users?role=${role.name}`} className={styles.members}>
                    {role.members} {role.members === 1 ? 'person' : 'people'}
                  </Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.actions.map((action) => (
              <tr key={action.key}>
                <th scope="row">
                  <span>{action.label}</span>
                  <span className={styles.sub}>{action.description}</span>
                </th>
                {data.roles.map((role) => {
                  const on = granted(role).includes(action.key)
                  const locked = role.locked.includes(action.key)
                  return (
                    <td key={role.id}>
                      <input
                        type="checkbox"
                        aria-label={`${role.label} can ${action.label.toLowerCase()}`}
                        checked={on}
                        disabled={locked || saving !== null}
                        title={locked ? 'Admins always keep this' : undefined}
                        onChange={(e) => void toggle(role, action.key, e.target.checked)}
                      />
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.roles.some((r) => !r.builtin) && (
        <section className={styles.section} aria-labelledby="custom-roles">
          <h2 id="custom-roles">Roles you added</h2>
          <ul className={styles.rows}>
            {data.roles
              .filter((r) => !r.builtin)
              .map((role) => (
                <li key={role.id}>
                  <div>
                    <strong>{role.label}</strong>
                    <p className={styles.sub}>
                      <Link to={`/admin/users?role=${role.name}`}>
                        {role.members} {role.members === 1 ? 'person' : 'people'}
                      </Link>
                    </p>
                  </div>
                  <span className={styles.buttons}>
                    <button type="button" className="btn" onClick={() => setRenaming(role)}>
                      Rename
                    </button>
                    <button type="button" className="btn" onClick={() => setDeleting(role)}>
                      Delete
                    </button>
                  </span>
                </li>
              ))}
          </ul>
        </section>
      )}

      {adding && (
        <AddRoleDialog
          actions={data.actions}
          onClose={() => setAdding(false)}
          onCreated={(role) => {
            setAdding(false)
            setMessage(`Added the ${role.label} role.`)
            reload()
          }}
        />
      )}
      {renaming && (
        <RenameRoleDialog
          role={renaming}
          onClose={() => setRenaming(null)}
          onRenamed={() => {
            setRenaming(null)
            setMessage('Renamed.')
            reload()
          }}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title={`Delete ${deleting.label}?`}
          confirmLabel="Delete role"
          busy={busy}
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            const role = deleting
            setBusy(true)
            setProblem(null)
            adminApi
              .deleteRole(role.id)
              .then(() => {
                setMessage(`Deleted the ${role.label} role.`)
                reload()
              })
              .catch((err) =>
                setProblem(err instanceof Error ? err.message : 'We couldn’t delete that role.'),
              )
              .finally(() => {
                setBusy(false)
                setDeleting(null)
              })
          }}
        >
          This removes the role and what it allowed. Nobody holds it right now, and the deletion is
          recorded in the audit log.
        </ConfirmDialog>
      )}
    </AdminPage>
  )
}
