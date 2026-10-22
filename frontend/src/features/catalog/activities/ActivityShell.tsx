import type { ReactNode } from 'react'

import { Icon, type IconName } from '../../../components/Icon'
import styles from './ActivityShell.module.css'

interface Props {
  icon: IconName
  title: string
  /** Quiet second line: kind, time, required/optional. */
  meta: string
  done?: boolean
  /** Finished without a pass (a quiz out of attempts): quiet and grayed, not an alarm. */
  muted?: boolean
  /** Right-hand side: the activity's own actions or state. */
  children?: ReactNode
  /** Room beneath the row for an activity that opens in place (a quiz). */
  panel?: ReactNode
}

/** The one visual frame for every activity a learner meets, so each new type
 * (quiz, video…) looks like it belongs the moment it ships. */
export function ActivityShell({ icon, title, meta, done, muted, children, panel }: Props) {
  return (
    <div className={done ? styles.done : muted ? styles.muted : undefined}>
      <div className={styles.shell}>
        <span className={styles.tile} aria-hidden="true">
          <Icon name={done ? 'check' : icon} size={16} strokeWidth={done ? 2 : 1.5} />
        </span>
        <div className={styles.body}>
          <p className={styles.title}>{title}</p>
          <p className={styles.meta}>{meta}</p>
        </div>
        {children && <div className={styles.actions}>{children}</div>}
      </div>
      {panel && <div className={styles.panel}>{panel}</div>}
    </div>
  )
}
