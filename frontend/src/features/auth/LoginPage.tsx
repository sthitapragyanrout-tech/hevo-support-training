import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { Logo } from '../../components/Logo'
import { ApiError } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import styles from './LoginPage.module.css'

export function LoginPage() {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await auth.login(login, password)
      const redirectTo = (location.state as { from?: string } | null)?.from ?? '/'
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className={styles.page}>
      <section className={styles.intro} aria-hidden="true">
        <div className={styles.lockup}>
          <Logo size={32} />
          <span>
            <strong>Hevo</strong> Support Training
          </span>
        </div>
        <div className={styles.pitch}>
          <h2>Learn the work you’ll do for customers.</h2>
          <p>
            Pipelines, failures, logs and the conversations around them — taught the way they show
            up on real tickets.
          </p>
          <ol className={styles.flow}>
            {['Source', 'Pipeline', 'Destination'].map((step, i) => (
              <li key={step} className={i === 1 ? styles.on : ''}>
                {step}
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className={styles.formSide}>
        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.mobileBrand}>
            <Logo size={28} />
          </div>
          <h1>Sign in</h1>
          <p className={styles.sub}>Use your work email or username.</p>

          <label className={styles.field}>
            Email or username
            <input
              className="input"
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              autoFocus
              autoComplete="username"
            />
          </label>
          <label className={styles.field}>
            Password
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          {error && (
            <p role="alert" className={styles.error}>
              {error}
            </p>
          )}
          <button type="submit" className="btn btn-primary btn-lg" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
          <p className={styles.help}>Accounts are created by your administrator.</p>
        </form>
      </section>
    </main>
  )
}
