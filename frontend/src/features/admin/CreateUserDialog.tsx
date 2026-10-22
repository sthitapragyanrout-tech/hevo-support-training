import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Dialog } from '../../components/Dialog'
import { useCan } from '../../lib/capabilities'
import { CAN } from '../../lib/capabilityKeys'
import { adminApi, type UserDetail } from './adminApi'
import { useRoleOptions } from './useRoles'
import styles from './people.module.css'

interface Props {
  onClose: () => void
  onCreated: () => void
}

/** Add a person. If no password is typed one is generated and shown once. */
export function CreateUserDialog({ onClose, onCreated }: Props) {
  const canAssign = useCan(CAN.manageRoles)
  const roleChoices = useRoleOptions()
  const [email, setEmail] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [employeeId, setEmployeeId] = useState('')
  const [role, setRole] = useState('learner')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [created, setCreated] = useState<UserDetail | null>(null)
  const [copied, setCopied] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      const user = await adminApi.createUser({
        email,
        first_name: firstName,
        last_name: lastName,
        employee_id: employeeId,
        password,
        ...(canAssign ? { roles: [role] } : {}),
      })
      setCreated(user)
      onCreated()
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t create that user.')
    } finally {
      setBusy(false)
    }
  }

  if (created) {
    const temp = created.temporary_password
    return (
      <Dialog
        title="User added"
        onClose={onClose}
        actions={
          <>
            <Link to={`/admin/users/${created.id}`} className="btn" onClick={onClose}>
              Open {created.name}
            </Link>
            <button type="button" className="btn btn-primary" onClick={onClose}>
              Done
            </button>
          </>
        }
      >
        <p>
          <strong>{created.name}</strong> can sign in with {created.email}.
        </p>
        {temp ? (
          <div className={styles.secret}>
            <p className={styles.sub}>
              Temporary password — shown once. Give it to them securely; they should change it
              at first sign-in.
            </p>
            <div className={styles.secretRow}>
              <code>{temp}</code>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  void navigator.clipboard?.writeText(temp)
                  setCopied(true)
                }}
              >
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          </div>
        ) : (
          <p className={styles.sub}>
            They should change the password you set at first sign-in.
          </p>
        )}
      </Dialog>
    )
  }

  return (
    <Dialog
      title="Add a user"
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            form="create-user"
            className="btn btn-primary"
            disabled={busy || !email.trim()}
          >
            {busy ? 'Adding…' : 'Add user'}
          </button>
        </>
      }
    >
      <form id="create-user" className={styles.form} onSubmit={(e) => void submit(e)}>
        <label className={styles.field}>
          <span>Email</span>
          <input
            className="input"
            type="email"
            autoComplete="off"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <div className={styles.pair}>
          <label className={styles.field}>
            <span>First name</span>
            <input className="input" value={firstName} onChange={(e) => setFirstName(e.target.value)} />
          </label>
          <label className={styles.field}>
            <span>Last name</span>
            <input className="input" value={lastName} onChange={(e) => setLastName(e.target.value)} />
          </label>
        </div>
        <div className={styles.pair}>
          <label className={styles.field}>
            <span>Employee id (optional)</span>
            <input
              className="input"
              value={employeeId}
              onChange={(e) => setEmployeeId(e.target.value)}
            />
          </label>
          {canAssign && (
            <label className={styles.field}>
              <span>Role</span>
              <select className="input" value={role} onChange={(e) => setRole(e.target.value)}>
                {roleChoices.options.map((o) => (
                  <option key={o.name} value={o.name}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <label className={styles.field}>
          <span>Password (optional)</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <small className={styles.sub}>Leave blank to generate a temporary one.</small>
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
