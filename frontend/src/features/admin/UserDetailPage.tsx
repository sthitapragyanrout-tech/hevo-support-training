import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { PageState } from '../../components/PageState'
import { useCan } from '../../lib/capabilities'
import { CAN } from '../../lib/capabilityKeys'
import { ConfirmDialog } from '../studio/ConfirmDialog'
import { AdminPage } from './AdminPage'
import { adminApi, type UserChanges, type UserDetail } from './adminApi'
import { accountState, formatDateTime } from './format'
import { useRoleOptions } from './useRoles'
import { SetPasswordDialog } from './SetPasswordDialog'
import { useQuery } from './useQuery'
import styles from './people.module.css'

export function UserDetailPage() {
  const { userId = '' } = useParams()
  const { data, loading, error, errorStatus, reload } = useQuery(
    () => adminApi.user(userId),
    `user-${userId}`,
  )
  if (loading) return <PageState kind="loading" />
  if (errorStatus === 404) return <PageState kind="empty" title="User not found" />
  if (error || !data) {
    return (
      <PageState kind="error" title="Couldn’t load this user" onRetry={reload}>
        {error}
      </PageState>
    )
  }
  return <UserEditor user={data} reload={reload} />
}

function UserEditor({ user, reload }: { user: UserDetail; reload: () => void }) {
  const canRoles = useCan(CAN.manageRoles)
  const [message, setMessage] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmActive, setConfirmActive] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)

  async function run(task: () => Promise<unknown>, done: string) {
    setBusy(true)
    setProblem(null)
    setMessage(null)
    try {
      await task()
      setMessage(done)
      reload()
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'That didn’t work. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const state = accountState(user)

  return (
    <AdminPage
      eyebrow="People · Users"
      title={user.name}
      hint={
        <>
          {user.email} · <span className={styles[`state_${state.toLowerCase()}`]}>{state}</span>
        </>
      }
      actions={
        <>
          <Link to={`/admin/results/learners/${user.id}`} className="btn">
            Results
          </Link>
          <Link to="/admin/users" className="btn">
            All users
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

      {/* Each form is re-keyed on what the server holds, so it starts from the
          saved values — while this page's status line survives a save. */}
      <ProfileSection
        key={[user.first_name, user.last_name, user.email, user.employee_id, user.timezone].join('|')}
        user={user}
        busy={busy}
        save={(c) => run(() => adminApi.updateUser(user.id, c), 'Saved.')} />

      {canRoles && (
        <RolesSection
          key={user.roles.join('|')}
          user={user}
          busy={busy}
          save={(roles) => run(() => adminApi.setUserRoles(user.id, roles), 'Roles saved.')}
        />
      )}

      <section className={styles.section} aria-labelledby="access">
        <h2 id="access">Access</h2>
        <ul className={styles.rows}>
          <li>
            <div>
              <strong>{user.is_active ? 'Active' : 'Deactivated'}</strong>
              <p className={styles.sub}>
                {user.is_active
                  ? 'They can sign in. Deactivating keeps their history but stops them signing in.'
                  : 'They can’t sign in. Their history is kept.'}
              </p>
            </div>
            <button
              type="button"
              className="btn"
              disabled={busy || (user.is_self && user.is_active)}
              title={user.is_self && user.is_active ? 'You can’t deactivate yourself' : undefined}
              onClick={() => setConfirmActive(true)}
            >
              {user.is_active ? 'Deactivate' : 'Reactivate'}
            </button>
          </li>
          <li>
            <div>
              <strong>Password</strong>
              <p className={styles.sub}>
                {user.must_change_password
                  ? 'Marked to choose a new one at next sign-in.'
                  : 'Set by them.'}
              </p>
            </div>
            <span className={styles.buttons}>
              {!user.must_change_password && (
                <button
                  type="button"
                  className="btn"
                  disabled={busy}
                  onClick={() =>
                    void run(
                      () => adminApi.updateUser(user.id, { must_change_password: true }),
                      'Marked to change their password at next sign-in.',
                    )
                  }
                >
                  Require a change
                </button>
              )}
              <button type="button" className="btn" disabled={busy} onClick={() => setPasswordOpen(true)}>
                Set password
              </button>
            </span>
          </li>
          {user.locked && (
            <li>
              <div>
                <strong>Locked out</strong>
                <p className={styles.sub}>Too many failed sign-ins. This clears by itself after a while.</p>
              </div>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => void run(() => adminApi.unlock(user.id), 'Unlocked.')}
              >
                Unlock now
              </button>
            </li>
          )}
        </ul>
      </section>

      <PrivilegesSection
        key={`${user.is_staff}|${user.is_superuser}`}
        user={user}
        busy={busy}
        save={(c) => run(() => adminApi.updateUser(user.id, c), 'Access saved.')}
      />

      <section className={styles.section} aria-labelledby="signins">
        <h2 id="signins">Sign-in</h2>
        <dl className={styles.facts}>
          <div>
            <dt>Username</dt>
            <dd>{user.username}</dd>
          </div>
          <div>
            <dt>Joined</dt>
            <dd>{formatDateTime(user.date_joined)}</dd>
          </div>
          <div>
            <dt>Last sign-in</dt>
            <dd>
              {user.last_login ? formatDateTime(user.last_login) : 'Never'} ·{' '}
              <Link to={`/admin/signins?search=${encodeURIComponent(user.username)}`}>
                Sign-in activity
              </Link>
            </dd>
          </div>
          {user.identities.map((i) => (
            <div key={`${i.provider}-${i.external_id}`}>
              <dt>Identity</dt>
              <dd>
                {i.provider} · {i.external_id}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      {confirmActive && (
        <ConfirmDialog
          title={user.is_active ? `Deactivate ${user.name}?` : `Reactivate ${user.name}?`}
          confirmLabel={user.is_active ? 'Deactivate' : 'Reactivate'}
          busy={busy}
          onCancel={() => setConfirmActive(false)}
          onConfirm={() => {
            setConfirmActive(false)
            void run(
              () => adminApi.updateUser(user.id, { is_active: !user.is_active }),
              user.is_active ? 'Deactivated.' : 'Reactivated.',
            )
          }}
        >
          {user.is_active
            ? 'They will be signed out and won’t be able to sign in. Their progress and scores are kept, and you can reactivate them any time. This is recorded in the audit log.'
            : 'They will be able to sign in again. This is recorded in the audit log.'}
        </ConfirmDialog>
      )}
      {passwordOpen && (
        <SetPasswordDialog
          userId={user.id}
          name={user.name}
          onClose={() => {
            setPasswordOpen(false)
            reload()
          }}
        />
      )}
    </AdminPage>
  )
}

function ProfileSection({
  user,
  busy,
  save,
}: {
  user: UserDetail
  busy: boolean
  save: (changes: UserChanges) => Promise<void>
}) {
  const [form, setForm] = useState({
    first_name: user.first_name,
    last_name: user.last_name,
    email: user.email,
    employee_id: user.employee_id ?? '',
    timezone: user.timezone,
  })
  const dirty =
    form.first_name !== user.first_name ||
    form.last_name !== user.last_name ||
    form.email !== user.email ||
    form.employee_id !== (user.employee_id ?? '') ||
    form.timezone !== user.timezone
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: e.target.value })

  return (
    <section className={styles.section} aria-labelledby="profile">
      <h2 id="profile">Profile</h2>
      <form
        className={styles.form}
        onSubmit={(e) => {
          e.preventDefault()
          void save({ ...form, employee_id: form.employee_id || null })
        }}
      >
        <div className={styles.pair}>
          <label className={styles.field}>
            <span>First name</span>
            <input className="input" value={form.first_name} onChange={set('first_name')} />
          </label>
          <label className={styles.field}>
            <span>Last name</span>
            <input className="input" value={form.last_name} onChange={set('last_name')} />
          </label>
        </div>
        <label className={styles.field}>
          <span>Email</span>
          <input className="input" type="email" value={form.email} onChange={set('email')} />
        </label>
        <div className={styles.pair}>
          <label className={styles.field}>
            <span>Employee id</span>
            <input className="input" value={form.employee_id} onChange={set('employee_id')} />
          </label>
          <label className={styles.field}>
            <span>Time zone</span>
            <input className="input" value={form.timezone} onChange={set('timezone')} />
          </label>
        </div>
        <div>
          <button type="submit" className="btn btn-primary" disabled={!dirty || busy}>
            Save profile
          </button>
        </div>
      </form>
    </section>
  )
}

function RolesSection({
  user,
  busy,
  save,
}: {
  user: UserDetail
  busy: boolean
  save: (roles: string[]) => Promise<void>
}) {
  const [roles, setRoles] = useState<string[]>(user.roles)
  const roleChoices = useRoleOptions()
  const dirty = roles.slice().sort().join() !== user.roles.slice().sort().join()
  const toggle = (name: string) =>
    setRoles(roles.includes(name) ? roles.filter((r) => r !== name) : [...roles, name])

  return (
    <section className={styles.section} aria-labelledby="roles">
      <h2 id="roles">Roles</h2>
      <p className={styles.sub}>What someone can do comes only from their roles.</p>
      <fieldset className={styles.checks}>
        <legend className="sr-only">Roles</legend>
        {roleChoices.options.map((o) => (
          <label key={o.name}>
            <input
              type="checkbox"
              checked={roles.includes(o.name)}
              onChange={() => toggle(o.name)}
            />
            {o.label}
          </label>
        ))}
      </fieldset>
      <div>
        <button type="button" className="btn btn-primary" disabled={!dirty || busy} onClick={() => void save(roles)}>
          Save roles
        </button>
      </div>
    </section>
  )
}

function PrivilegesSection({
  user,
  busy,
  save,
}: {
  user: UserDetail
  busy: boolean
  save: (changes: UserChanges) => Promise<void>
}) {
  const [staff, setStaff] = useState(user.is_staff)
  const [superuser, setSuperuser] = useState(user.is_superuser)
  const dirty = staff !== user.is_staff || superuser !== user.is_superuser

  return (
    <section className={styles.section} aria-labelledby="privileges">
      <h2 id="privileges">Emergency access</h2>
      <p className={styles.sub}>
        Superusers can use the emergency back-office and bypass role checks. Only a superuser can change
        this.
      </p>
      <fieldset className={styles.checks} disabled={!user.can_edit_privileges}>
        <legend className="sr-only">Emergency access</legend>
        <label>
          <input type="checkbox" checked={staff} onChange={(e) => setStaff(e.target.checked)} />
          Staff
        </label>
        <label>
          <input type="checkbox" checked={superuser} onChange={(e) => setSuperuser(e.target.checked)} />
          Superuser
        </label>
      </fieldset>
      {user.can_edit_privileges && (
        <div>
          <button
            type="button"
            className="btn"
            disabled={!dirty || busy}
            onClick={() => void save({ is_staff: staff, is_superuser: superuser })}
          >
            Save access
          </button>
        </div>
      )}
    </section>
  )
}
