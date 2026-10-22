import type { ReactNode } from 'react'

import styles from './AdminPage.module.css'

interface Props {
  eyebrow: string
  title: string
  /** Quiet line under the title. */
  hint?: ReactNode
  /** Buttons/links on the right of the header. */
  actions?: ReactNode
  children: ReactNode
}

/** The frame every console screen shares: eyebrow, title, actions, content. */
export function AdminPage({ eyebrow, title, hint, actions, children }: Props) {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          {hint && <p className={styles.hint}>{hint}</p>}
        </div>
        {actions && <div className={styles.actions}>{actions}</div>}
      </header>
      {children}
    </div>
  )
}

/** A search box + filters row above a table. */
export function Toolbar({ children }: { children: ReactNode }) {
  return <div className={styles.toolbar}>{children}</div>
}
