import { Icon } from './Icon'
import styles from './StatusIcon.module.css'

export type LessonStatus = 'not_started' | 'current' | 'completed'

const LABELS: Record<LessonStatus, string> = {
  not_started: 'Not started',
  current: 'Current lesson',
  completed: 'Completed',
}

/** Status is icon *and* text (visually hidden) — never color alone. */
export function StatusIcon({ status }: { status: LessonStatus }) {
  return (
    <span className={`${styles.icon} ${styles[status]}`}>
      {status === 'completed' && <Icon name="check" size={12} strokeWidth={2} />}
      {status === 'current' && <span className={styles.dot} />}
      <span className="sr-only">{LABELS[status]}</span>
    </span>
  )
}
