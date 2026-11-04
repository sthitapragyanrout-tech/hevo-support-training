import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { StatusIcon, type LessonStatus } from '../../components/StatusIcon'
import { ACTIVITY_LABELS, activityIcon, primaryActivity } from './activityTypes'
import styles from './LessonItem.module.css'
import { formatMinutes, lessonMinutes, summarize, type Lesson } from './treeUtils'

interface Props {
  basePath: string
  lesson: Lesson
  status: LessonStatus
  /** Is this the lesson being read? (Independent of status: a lesson can be
   * both current and completed.) Defaults to `status === 'current'`. */
  current?: boolean
  /** `compact` = sidebar row; `detailed` = landing row with summary. */
  variant: 'compact' | 'detailed'
  /** Why this lesson is locked, if it is ("Unlocks when you complete …"). */
  lockedHint?: string | null
  onNavigate?: () => void
}

export function LessonItem({
  basePath,
  lesson,
  status,
  current: isCurrent,
  variant,
  lockedHint,
  onNavigate,
}: Props) {
  const { node } = lesson
  const current = isCurrent ?? status === 'current'
  const summary = variant === 'detailed' ? summarize(node.description) : ''
  const primary = primaryActivity(lesson)
  const minutes = lessonMinutes(lesson)
  const locked = status === 'locked'

  // In the sidebar a locked lesson is a quiet, non-interactive row. On the
  // landing it stays a link, so the explanation is one click away.
  if (locked && variant === 'compact') {
    return (
      <span
        className={`${styles.item} ${styles[variant]} ${styles.locked}`}
        aria-disabled="true"
        title={lockedHint ?? undefined}
      >
        <span className={styles.status}>
          <StatusIcon status={status} />
        </span>
        <span className={styles.text}>
          <span className={styles.title}>{node.title}</span>
        </span>
      </span>
    )
  }

  return (
    <Link
      to={`${basePath}/lessons/${node.id}`}
      className={`${styles.item} ${styles[variant]} ${current ? styles.current : ''} ${
        locked ? styles.locked : ''
      }`}
      aria-current={current ? 'page' : undefined}
      onClick={onNavigate}
    >
      <span className={styles.status}>
        <StatusIcon status={status} />
      </span>
      <span className={styles.text}>
        <span className={styles.title}>{node.title}</span>
        {locked && lockedHint ? (
          <span className={styles.summary}>{lockedHint}</span>
        ) : (
          summary && <span className={styles.summary}>{summary}</span>
        )}
        {status === 'next' && variant === 'detailed' && (
          <span className={styles.upNext}>Up next</span>
        )}
      </span>
      <span className={styles.aside}>
        {primary && (
          <span className={styles.type} title={ACTIVITY_LABELS[primary.activity_type]}>
            <Icon name={activityIcon(primary.activity_type)} size={14} />
            <span className="sr-only">{ACTIVITY_LABELS[primary.activity_type]}</span>
          </span>
        )}
        {variant === 'detailed' && minutes != null && (
          <span className={styles.minutes}>{formatMinutes(minutes)}</span>
        )}
      </span>
    </Link>
  )
}
