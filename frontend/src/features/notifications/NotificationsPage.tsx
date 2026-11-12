import { useCallback, useEffect, useState } from 'react'

import { PageState } from '../../components/PageState'
import { notificationsApi, type AppNotification, type NotificationPage } from '../../lib/api'
import { useNotificationCount } from './NotificationsContext'
import { NotificationItem } from './NotificationItem'
import styles from './Notifications.module.css'

/** Everything you have been told, newest first, with what is still unread. */
export function NotificationsPage() {
  const { setUnread } = useNotificationCount()
  const [page, setPage] = useState(1)
  const [data, setData] = useState<NotificationPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(
    async (n: number) => {
      setError(null)
      try {
        const result = await notificationsApi.list({ page: n })
        setData(result)
        setUnread(result.unread_count)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'We couldn’t load your notifications.')
      }
    },
    [setUnread],
  )

  useEffect(() => {
    void load(page)
  }, [load, page])

  function open(n: AppNotification) {
    // The link navigates; reading it is a side effect that must not block that.
    if (!n.read) {
      notificationsApi
        .read(n.id)
        .then((r) => setUnread(r.unread_count))
        .catch(() => {})
      setData(
        (d) =>
          d && { ...d, results: d.results.map((x) => (x.id === n.id ? { ...x, read: true } : x)) },
      )
    }
  }

  async function markAll() {
    setBusy(true)
    try {
      const r = await notificationsApi.readAll()
      setUnread(r.unread_count)
      setData(
        (d) =>
          d && { ...d, unread_count: 0, results: d.results.map((x) => ({ ...x, read: true })) },
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That didn’t work. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  if (error && !data) {
    return (
      <PageState
        kind="error"
        title="Couldn’t load your notifications"
        onRetry={() => void load(page)}
      >
        {error}
      </PageState>
    )
  }
  if (!data) return <PageState kind="loading" />

  return (
    <div className={styles.page}>
      <header className={styles.pageHead}>
        <div>
          <p className="eyebrow">Updates</p>
          <h1 className={styles.heading}>Notifications</h1>
        </div>
        <button
          type="button"
          className="btn btn-sm"
          disabled={busy || data.unread_count === 0}
          onClick={() => void markAll()}
        >
          Mark all read
        </button>
      </header>
      {error && (
        <p role="alert" className={styles.note}>
          {error}
        </p>
      )}
      {data.results.length === 0 ? (
        <p className={styles.empty}>You’re all caught up. Nothing has changed that needs you.</p>
      ) : (
        <ul className={styles.list} aria-label="Your notifications">
          {data.results.map((n) => (
            <li key={n.id}>
              <NotificationItem n={n} onOpen={open} />
            </li>
          ))}
        </ul>
      )}
      {data.pages > 1 && (
        <nav className={styles.pager} aria-label="Pages">
          <button
            type="button"
            className="btn btn-sm"
            disabled={data.page <= 1}
            onClick={() => setPage(data.page - 1)}
          >
            Newer
          </button>
          <span className={styles.note}>
            Page {data.page} of {data.pages}
          </span>
          <button
            type="button"
            className="btn btn-sm"
            disabled={data.page >= data.pages}
            onClick={() => setPage(data.page + 1)}
          >
            Older
          </button>
        </nav>
      )}
    </div>
  )
}
