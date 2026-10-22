import type { CourseStatus } from './types'
import styles from './StatusChip.module.css'

/** A dot and a word — status is never color alone. */
export function StatusChip({ status }: { status: CourseStatus }) {
  return (
    <span className={`${styles.chip} ${styles[status.key]}`}>
      <span className={styles.dot} aria-hidden="true" />
      {status.label}
    </span>
  )
}
