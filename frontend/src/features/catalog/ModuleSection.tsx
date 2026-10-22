import { useId } from 'react'

import { Icon } from '../../components/Icon'
import type { LessonStatus } from '../../components/StatusIcon'
import { LessonItem } from './LessonItem'
import { ModuleMarker } from './ModuleMarker'
import styles from './ModuleSection.module.css'
import { formatMinutes, pluralize, summarize, totalMinutes, type Lesson, type Module } from './treeUtils'

interface Props {
  basePath: string
  module: Module
  /** Lessons to show (the full list, or a filtered subset). */
  lessons: Lesson[]
  statusOf: (lesson: Lesson) => LessonStatus
  markerState: 'default' | 'current' | 'complete'
  /** The lesson being read, if any (sidebar). */
  currentId?: number | null
  /** Sidebar: collapsible disclosure. Landing: always-open journey stop. */
  variant: 'compact' | 'detailed'
  open?: boolean
  onToggle?: () => void
  onNavigate?: () => void
}

export function ModuleSection({
  basePath,
  module,
  lessons,
  statusOf,
  markerState,
  currentId,
  variant,
  open = true,
  onToggle,
  onNavigate,
}: Props) {
  const listId = useId()
  const minutes = totalMinutes(module.lessons)
  const meta = [
    pluralize(module.lessons.length, 'lesson'),
    minutes != null ? formatMinutes(minutes) : null,
  ]
    .filter(Boolean)
    .join(' · ')

  const list = (
    <ul id={listId} className={styles.list}>
      {lessons.map((lesson) => (
        <li key={lesson.node.id}>
          <LessonItem
            basePath={basePath}
            lesson={lesson}
            status={statusOf(lesson)}
            current={currentId === undefined ? undefined : lesson.node.id === currentId}
            variant={variant}
            onNavigate={onNavigate}
          />
        </li>
      ))}
    </ul>
  )

  if (variant === 'compact') {
    return (
      <section className={styles.compact}>
        <h3 className={styles.compactHeading}>
          <button
            type="button"
            className={styles.toggle}
            aria-expanded={open}
            aria-controls={listId}
            onClick={onToggle}
          >
            <ModuleMarker number={module.number} state={markerState} size="sm" />
            <span className={styles.compactTitle}>
              <span className="sr-only">Module {module.number}: </span>
              {module.node.title}
            </span>
            <span className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}>
              <Icon name="chevronRight" size={14} />
            </span>
          </button>
        </h3>
        {open && list}
      </section>
    )
  }

  const summary = summarize(module.node.description, 200)
  return (
    <section className={styles.detailed} aria-labelledby={`${listId}-title`}>
      <div className={styles.marker}>
        <ModuleMarker number={module.number} state={markerState} />
      </div>
      <header className={styles.detailedHeader}>
        <div>
          <h3 id={`${listId}-title`} className={styles.detailedTitle}>
            <span className="sr-only">Module {module.number}: </span>
            {module.node.title}
          </h3>
          {summary && <p className={styles.summary}>{summary}</p>}
        </div>
        <p className={styles.meta}>{meta}</p>
      </header>
      <div className={styles.lessons}>{list}</div>
    </section>
  )
}
