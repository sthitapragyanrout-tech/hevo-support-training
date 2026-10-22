import type { ReactNode } from 'react'

import styles from './PageState.module.css'

interface Props {
  kind: 'loading' | 'error' | 'empty'
  title?: string
  children?: ReactNode
  onRetry?: () => void
}

/** One component for the three non-content states of any route. */
export function PageState({ kind, title, children, onRetry }: Props) {
  if (kind === 'loading') {
    return (
      <div className={styles.wrap} role="status" aria-live="polite">
        <span className="sr-only">Loading…</span>
        <div className={styles.skeleton} style={{ width: '40%', height: 28 }} />
        <div className={styles.skeleton} style={{ width: '90%' }} />
        <div className={styles.skeleton} style={{ width: '75%' }} />
        <div className={styles.skeleton} style={{ width: '82%' }} />
      </div>
    )
  }
  return (
    <div className={styles.wrap} role={kind === 'error' ? 'alert' : undefined}>
      {title && <h1 className={styles.title}>{title}</h1>}
      {children && <p className={styles.body}>{children}</p>}
      {kind === 'error' && onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}
