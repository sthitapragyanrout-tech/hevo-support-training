import { Link } from 'react-router-dom'

import { Icon } from '../components/Icon'
import { Popover } from '../components/Popover'
import { useAuth } from '../lib/auth'
import styles from './UserMenu.module.css'

export function UserMenu() {
  const { user, logout } = useAuth()
  if (!user) return null

  const name = user.email || user.username
  const initial = name.charAt(0).toUpperCase()
  // Django Admin is break-glass now: superusers only, under /django-admin/.
  const backOffice = user.is_superuser === true

  return (
    <div className={styles.root}>
      <Popover
        label="Account"
        align="end"
        width={260}
        trigger={(props) => (
          <button type="button" className={styles.trigger} aria-label="Account menu" {...props}>
            <span className={styles.avatar} aria-hidden="true">
              {initial}
            </span>
            <Icon name="chevronDown" size={14} />
          </button>
        )}
      >
        {() => (
          <div className={styles.panel}>
            <p className={styles.email}>{name}</p>
            {user.roles.length > 0 && <p className={styles.roles}>{user.roles.join(' · ')}</p>}
            <div className={styles.actions}>
              <Link to="/account/password" className={styles.item}>
                Change password
              </Link>
              {backOffice && (
                <a href="/django-admin/" className={styles.item}>
                  Emergency back-office
                  <span className={styles.hint}>Django admin · superusers</span>
                </a>
              )}
              <button type="button" className={styles.item} onClick={() => void logout()}>
                Log out
              </button>
            </div>
          </div>
        )}
      </Popover>
    </div>
  )
}
