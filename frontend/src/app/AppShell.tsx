import { Link, NavLink, Outlet } from 'react-router-dom'

import { Logo } from '../components/Logo'
import { useAuth } from '../lib/auth'
import { useCan, useCanAny } from '../lib/capabilities'
import { CAN } from '../lib/capabilityKeys'
import styles from './AppShell.module.css'
import { UserMenu } from './UserMenu'

/** One shell for every role. What appears in the navigation comes from the
 * server-reported capabilities, so a learner, trainer and admin all see the
 * same product with more or fewer doors. */
export function AppShell() {
  const { user } = useAuth()
  // Until a temporary password is replaced, there is nowhere else to go.
  const forcedChange = user?.password_change_required === true
  const canAuthor = useCan(CAN.authorContent)
  const canAdmin = useCanAny([
    CAN.viewResults,
    CAN.viewAudit,
    CAN.manageUsers,
    CAN.manageRoles,
    CAN.rateSimulations,
    CAN.manageReviews,
  ])

  return (
    <div className={styles.shell}>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <header className={styles.header}>
        <Link to="/" className={styles.brand} aria-label="Hevo Support Training — home">
          <Logo size={26} />
          <span className={styles.name}>
            <span className={styles.hevo}>Hevo</span> Support Training
          </span>
        </Link>
        {!forcedChange && (
          <nav className={styles.nav} aria-label="Main">
            <NavLink to="/" end className={({ isActive }) => (isActive ? styles.active : '')}>
              My courses
            </NavLink>
            {canAuthor && (
              <NavLink to="/studio" className={({ isActive }) => (isActive ? styles.active : '')}>
                Studio
              </NavLink>
            )}
            {canAdmin && (
              <NavLink to="/admin" className={({ isActive }) => (isActive ? styles.active : '')}>
                Admin
              </NavLink>
            )}
          </nav>
        )}
        <UserMenu />
      </header>
      <main id="main" tabIndex={-1} className={styles.main}>
        <Outlet />
      </main>
    </div>
  )
}
