import { Link } from 'react-router-dom'

import type { AppNotification } from '../../lib/api'
import { timeAgo } from './format'
import styles from './Notifications.module.css'

interface Props {
  n: AppNotification
  /** Called when the person opens it (the caller marks it read). */
  onOpen: (n: AppNotification) => void
}

/** One notification: its title and text, how long ago, and where it takes you. An unread one is
 * marked with a dot (and says so to a screen reader), never with colour alone. */
export function NotificationItem({ n, onOpen }: Props) {
  const content = (
    <>
      <span className={styles.dot} data-unread={!n.read || undefined} aria-hidden="true" />
      <span className={styles.text}>
        <span className={styles.title}>
          {!n.read && <span className="sr-only">Unread: </span>}
          {n.title}
        </span>
        {n.body && <span className={styles.body}>{n.body}</span>}
        <span className={styles.when}>{timeAgo(n.created_at)}</span>
      </span>
    </>
  )
  return n.link ? (
    <Link
      to={n.link}
      className={styles.item}
      data-unread={!n.read || undefined}
      onClick={() => onOpen(n)}
    >
      {content}
    </Link>
  ) : (
    <button
      type="button"
      className={styles.item}
      data-unread={!n.read || undefined}
      onClick={() => onOpen(n)}
    >
      {content}
    </button>
  )
}
