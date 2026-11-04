import { Icon } from './Icon'
import styles from './StatusIcon.module.css'

export type LessonStatus = 'not_started' | 'current' | 'next' | 'locked' | 'completed'

const LABELS: Record<LessonStatus, string> = {
  not_started: 'Not started',
  current: 'Current lesson',
  next: 'Up next',
  locked: 'Locked',
  completed: 'Completed',
}

/** Status is icon *and* text (visually hidden) — never color alone. */
export function StatusIcon({ status }: { status: LessonStatus }) {
  return (
    <span className={`${styles.icon} ${styles[status]}`}>
      {status === 'completed' && <Icon name="check" size={12} strokeWidth={2} />}
      {status === 'current' && <span className={styles.dot} />}
      {status === 'next' && <Icon name="arrowRight" size={10} strokeWidth={2} />}
      {status === 'locked' && <Icon name="lock" size={10} strokeWidth={1.75} />}
      <span className="sr-only">{LABELS[status]}</span>
    </span>
  )
}
