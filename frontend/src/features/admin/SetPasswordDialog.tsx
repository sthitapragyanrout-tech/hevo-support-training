import { useState } from 'react'

import { Dialog } from '../../components/Dialog'
import { adminApi } from './adminApi'
import styles from './people.module.css'

interface Props {
  userId: number
  name: string
  onClose: () => void
}

/** Give someone a new password: type one, or let the server make one that is
 * shown a single time. Either way they must change it, and any open sessions end. */
export function SetPasswordDialog({ userId, name, onClose }: Props) {
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [generated, setGenerated] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [copied, setCopied] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      const result = await adminApi.setPassword(userId, password)
      setGenerated(result.temporary_password ?? null)
      setDone(true)
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t set that password.')
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <Dialog
        title="Password set"
        onClose={onClose}
        actions={
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Done
          </button>
        }
      >
        <p>
          {name} has been signed out everywhere and should choose a new password at their
          next sign-in.
        </p>
        {generated && (
          <div className={styles.secret}>
            <p className={styles.sub}>Temporary password — shown once.</p>
            <div className={styles.secretRow}>
              <code>{generated}</code>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  void navigator.clipboard?.writeText(generated)
                  setCopied(true)
                }}
              >
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          </div>
        )}
      </Dialog>
    )
  }

  return (
    <Dialog
      title="Set a new password"
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="set-password" className="btn btn-primary" disabled={busy}>
            {busy ? 'Saving…' : password ? 'Set password' : 'Generate password'}
          </button>
        </>
      }
    >
      <form id="set-password" className={styles.form} onSubmit={(e) => void submit(e)}>
        <p>
          This signs {name} out everywhere and makes them choose a new password next time. The change
          is recorded in the audit log (never the password itself).
        </p>
        <label className={styles.field}>
          <span>New password</span>
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
