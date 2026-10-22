import { NavLink, Navigate, Outlet } from 'react-router-dom'

import { useCan, useCanAny } from '../../lib/capabilities'
import { CAN } from '../../lib/capabilityKeys'
import styles from './AdminLayout.module.css'

interface Item {
  to: string
  label: string
  allowed: boolean
}

/** The console's frame: a quiet left rail of what this person may open. */
export function AdminLayout() {
  const canResults = useCan(CAN.viewResults)
  const canAudit = useCan(CAN.viewAudit)
  const canUsers = useCan(CAN.manageUsers)
  const canRoles = useCan(CAN.manageRoles)
  const canCourses = useCanAny([CAN.authorContent, CAN.publishCourse])

  const groups: { title: string; items: Item[] }[] = [
    {
      title: 'Results',
      items: [
        { to: '/admin/results/learners', label: 'Learners', allowed: canResults },
        { to: '/admin/results/quizzes', label: 'Quizzes', allowed: canResults },
      ],
    },
    {
      title: 'Content',
      items: [{ to: '/admin/courses', label: 'Courses', allowed: canCourses }],
    },
    {
      title: 'People',
      items: [
        { to: '/admin/users', label: 'Users', allowed: canUsers },
        { to: '/admin/roles', label: 'Roles', allowed: canRoles },
        { to: '/admin/signins', label: 'Sign-ins', allowed: canUsers },
      ],
    },
    {
      title: 'Activity',
      items: [{ to: '/admin/audit', label: 'Audit log', allowed: canAudit }],
    },
  ]
    .map((g) => ({ ...g, items: g.items.filter((i) => i.allowed) }))
    .filter((g) => g.items.length > 0)

  return (
    <div className={styles.layout}>
      <nav className={styles.rail} aria-label="Admin sections">
        {groups.map((group) => (
          <div key={group.title} className={styles.group}>
            <p className={styles.groupTitle}>{group.title}</p>
            <ul>
              {group.items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    className={({ isActive }) => `${styles.link} ${isActive ? styles.active : ''}`}
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      <div className={styles.content}>
        <Outlet />
      </div>
    </div>
  )
}

/** `/admin` itself: open the first screen this person may use. */
export function AdminIndex() {
  const canResults = useCan(CAN.viewResults)
  const canAudit = useCan(CAN.viewAudit)
  const canUsers = useCan(CAN.manageUsers)
  const canRoles = useCan(CAN.manageRoles)
  if (canResults) return <Navigate to="/admin/results/learners" replace />
  if (canUsers) return <Navigate to="/admin/users" replace />
  if (canRoles) return <Navigate to="/admin/roles" replace />
  if (canAudit) return <Navigate to="/admin/audit" replace />
  return null
}
