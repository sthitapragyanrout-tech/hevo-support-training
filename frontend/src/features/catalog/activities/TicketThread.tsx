import { useEffect, useRef } from 'react'

import type { SimThreadItem } from '../../../lib/api'
import styles from './SimActivity.module.css'

const time = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

/** The ticket's comments, oldest first, ticket-style: who wrote it and when. */
export function Thread({
  items,
  follow = false,
  finishing = false,
}: {
  items: SimThreadItem[]
  follow?: boolean
  /** The ticket is being closed, so a reply the customer couldn't answer isn't something to
   * retry by hand: it only needs scoring, which is retried automatically. */
  finishing?: boolean
}) {
  const end = useRef<HTMLLIElement>(null)
  const last = items[items.length - 1]?.seq
  useEffect(() => {
    if (follow) end.current?.scrollIntoView?.({ block: 'nearest' })
  }, [follow, last])

  return (
    <ol className={styles.thread} aria-label="Conversation" aria-live={follow ? 'polite' : undefined}>
      {items.map((item) => {
        const mine = item.role === 'intern'
        return (
          <li
            key={item.seq}
            className={`${styles.comment} ${mine ? styles.you : ''} ${item.kind !== 'message' ? styles.note : ''}`}
          >
            <p className={styles.who}>
              <span>{mine ? 'You' : 'Customer'}</span>
              <span className={styles.when}>{time(item.at)}</span>
            </p>
            <p className={styles.body}>{item.text}</p>
            {item.status === 'failed' && (
              <p className={styles.problem} role="alert">
                {finishing
                  ? 'This reply is still being scored. We’ll keep trying.'
                  : item.error || 'The customer couldn’t reply just now.'}
              </p>
            )}
          </li>
        )
      })}
      <li ref={end} aria-hidden="true" />
    </ol>
  )
}
