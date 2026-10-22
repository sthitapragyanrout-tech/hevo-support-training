import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../../lib/auth'
import styles from './ChangePasswordPage.module.css'

/** Change your own password. The same screen is the front door for anyone
 * signing in with a temporary or reset password, who must replace it first. */
export function ChangePasswordPage() {
  const { user, changePassword } = useAuth()
  const navigate = useNavigate()
  const forced = user?.password_change_required === true
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const mismatch = again !== '' && next !== again

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (next !== again) return setProblem('The two new passwords don’t match.')
    setBusy(true)
    setProblem(null)
    try {
      await changePassword(current, next)
      setCurrent('')
      setNext('')
      setAgain('')
      if (forced) navigate('/', { replace: true })
      else setDone(true)
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t change your password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.page}>
      <p className="eyebrow">Account</p>
      <h1>{forced ? 'Choose a new password' : 'Change your password'}</h1>
      <p className={styles.lead}>
        {forced
          ? 'You signed in with a temporary password. Choose your own to continue.'
          : 'You’ll stay signed in here; any other devices will be signed out.'}
      </p>

      {done && (
        <p role="status" className={styles.saved}>
          Your password has been changed.
        </p>
      )}

      <form className={styles.form} onSubmit={(e) => void submit(e)}>
        <label className={styles.field}>
          <span>{forced ? 'Temporary password' : 'Current password'}</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>New password</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
          <small>At least 8 characters, not too common, and not just numbers.</small>
        </label>
        <label className={styles.field}>
          <span>Confirm new password</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            aria-invalid={mismatch || undefined}
            value={again}
            onChange={(e) => setAgain(e.target.value)}
          />
          {mismatch && <small className={styles.problem}>These don’t match yet.</small>}
        </label>
        {problem && (
          <p role="alert" className={styles.problem}>
            {problem}
          </p>
        )}
        <div>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy || !current || !next || !again || mismatch}
          >
            {busy ? 'Saving…' : forced ? 'Set password and continue' : 'Change password'}
          </button>
        </div>
      </form>
    </div>
  )
}
