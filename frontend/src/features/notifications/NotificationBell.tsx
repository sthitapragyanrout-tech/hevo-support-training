import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { Popover } from '../../components/Popover'
import { notificationsApi, type AppNotification } from '../../lib/api'
import { useNotificationCount } from './NotificationsContext'
import { NotificationItem } from './NotificationItem'
import styles from './Notifications.module.css'

const LATEST = 8

/** The header bell: an unread count (nothing at zero) and, on click, the latest notifications. */
export function NotificationBell() {
  const { unread } = useNotificationCount()
  const label = unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'

  return (
    <div className={styles.bell}>
      <Popover
        label="Notifications"
        align="end"
        width={360}
        trigger={(props) => (
          <button type="button" className={styles.trigger} aria-label={label} {...props}>
            <Icon name="bell" size={18} />
            {unread > 0 && (
              <span className={styles.count} aria-hidden="true">
                {unread > 99 ? '99+' : unread}
              </span>
            )}
          </button>
        )}
      >
        {(close) => <Panel close={close} />}
      </Popover>
    </div>
  )
}

function Panel({ close }: { close: () => void }) {
  const { setUnread } = useNotificationCount()
  const [items, setItems] = useState<AppNotification[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let live = true
    notificationsApi
      .list({ page_size: LATEST })
      .then((page) => {
        if (!live) return
        setItems(page.results)
        setUnread(page.unread_count)
      })
      .catch(() => live && setFailed(true))
    return () => {
      live = false
    }
  }, [setUnread])

  function open(n: AppNotification) {
    close()
    if (n.read) return
    // Opening it is reading it: update the count at once, then tell the server.
    notificationsApi
      .read(n.id)
      .then((r) => setUnread(r.unread_count))
      .catch(() => {})
  }

  async function markAll() {
    setBusy(true)
    try {
      const r = await notificationsApi.readAll()
      setUnread(r.unread_count)
      setItems((list) => list?.map((n) => ({ ...n, read: true })) ?? list)
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  const anyUnread = items?.some((n) => !n.read) ?? false

  return (
    <div className={styles.panel}>
      <div className={styles.panelHead}>
        <h2 className={styles.panelTitle}>Notifications</h2>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={busy || !anyUnread}
          onClick={() => void markAll()}
        >
          Mark all read
        </button>
      </div>
      {failed && !items ? (
        <p className={styles.note} role="alert">
          We couldn’t load your notifications.
        </p>
      ) : items === null ? (
        <p className={styles.note}>Loading…</p>
      ) : items.length === 0 ? (
        <p className={styles.note}>You’re all caught up.</p>
      ) : (
        <ul className={styles.list}>
          {items.map((n) => (
            <li key={n.id}>
              <NotificationItem n={n} onOpen={open} />
            </li>
          ))}
        </ul>
      )}
      <Link to="/notifications" className={styles.seeAll} onClick={close}>
        See all notifications
      </Link>
    </div>
  )
}
