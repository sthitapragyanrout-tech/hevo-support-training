import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import type { LessonStatus } from '../../components/StatusIcon'
import type { CourseContext } from './courseContext'
import { LessonItem } from './LessonItem'
import { ModuleSection } from './ModuleSection'
import styles from './CourseSidebar.module.css'
import { lessonStatus, moduleMarker, unlockHint } from './lessonState'
import { searchLessons, type Lesson } from './treeUtils'

interface Props {
  course: CourseContext
  activeLessonId: number | null
  /** Called after a lesson link is followed (closes the mobile drawer). */
  onNavigate?: () => void
}

export function CourseSidebar({ course, activeLessonId, onNavigate }: Props) {
  const { basePath, root, modules, progress } = course
  const [toggled, setToggled] = useState<Record<number, boolean>>({})
  const [filtering, setFiltering] = useState(false)
  const [query, setQuery] = useState('')
  const input = useRef<HTMLInputElement>(null)

  const activeModuleId =
    modules.find((m) => m.lessons.some((l) => l.node.id === activeLessonId))?.node.id ?? null

  // Completed wins over current: a finished lesson you're re-reading keeps its
  // tick; "where you are" is carried by the tint, bar and aria-current.
  const statusOf = (lesson: Lesson): LessonStatus => lessonStatus(lesson, progress, activeLessonId)
  const lockedHintOf = (lesson: Lesson) => unlockHint(lesson, progress)

  function toggleFilter() {
    if (filtering) {
      setFiltering(false)
      setQuery('')
    } else {
      setFiltering(true)
      // Wait for the input to mount.
      setTimeout(() => input.current?.focus(), 0)
    }
  }

  const results = filtering && query.trim() ? searchLessons(modules, query) : null

  return (
    <nav className={styles.sidebar} aria-label="Course contents">
      <div className={styles.header}>
        <Link to={basePath} className={styles.courseTitle} onClick={onNavigate}>
          {root.title}
        </Link>
        <button
          type="button"
          className={styles.filterToggle}
          aria-label={filtering ? 'Close lesson filter' : 'Filter lessons'}
          aria-expanded={filtering}
          onClick={toggleFilter}
        >
          <Icon name={filtering ? 'close' : 'search'} size={15} />
        </button>
      </div>

      {filtering && (
        <div className={styles.filter}>
          <input
            ref={input}
            type="search"
            className={styles.filterInput}
            placeholder="Filter lessons"
            aria-label="Filter lessons"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.stopPropagation()
                toggleFilter()
              }
            }}
          />
        </div>
      )}

      {results ? (
        results.length === 0 ? (
          <p className={styles.empty}>No lessons match “{query.trim()}”.</p>
        ) : (
          <ul className={styles.results}>
            {results.map((lesson) => (
              <li key={lesson.node.id}>
                <LessonItem
                  basePath={basePath}
                  lesson={lesson}
                  status={statusOf(lesson)}
                  current={lesson.node.id === activeLessonId}
                  variant="compact"
                  lockedHint={lockedHintOf(lesson)}
                  onNavigate={onNavigate}
                />
              </li>
            ))}
          </ul>
        )
      ) : (
        modules.map((module) => (
          <ModuleSection
            key={module.node.id}
            basePath={basePath}
            module={module}
            lessons={module.lessons}
            statusOf={statusOf}
            currentId={activeLessonId}
            lockedHintOf={lockedHintOf}
            markerState={moduleMarker(module, progress, activeModuleId)}
            variant="compact"
            open={toggled[module.node.id] ?? module.node.id === activeModuleId}
            onToggle={() =>
              setToggled((t) => ({
                ...t,
                [module.node.id]: !(t[module.node.id] ?? module.node.id === activeModuleId),
              }))
            }
            onNavigate={onNavigate}
          />
        ))
      )}
    </nav>
  )
}
