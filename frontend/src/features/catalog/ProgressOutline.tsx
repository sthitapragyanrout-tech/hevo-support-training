import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { ProgressBar } from '../../components/ProgressBar'
import type { ProgressLesson, ProgressModule } from '../../lib/api'
import { ModuleMarker } from './ModuleMarker'
import { Go } from './ProgressScores'
import styles from './ProgressOutline.module.css'
import { pluralize } from './treeUtils'

export interface OutlineCourse {
  course_id: number
  title: string
  lessons_done: number
  lessons_total: number
  lessons_awaiting_review: number
  modules: ProgressModule[]
}

interface Props {
  /** Names the panel, e.g. "Your courses" or "Ann's courses". */
  label: string
  courses: OutlineCourse[]
  selected: OutlineCourse
  /** Where picking a course goes (the same page, with the course in the URL). */
  courseHref: (courseId: number) => string
  /** Where a lesson links to; null leaves it as plain text. */
  lessonHref: (lessonId: number) => string | null
  /** Lesson links are anchors on this page rather than routes. */
  anchors?: boolean
}

const MARKER: Record<ProgressModule['state'], 'complete' | 'current' | 'default'> = {
  done: 'complete',
  in_progress: 'current',
  not_started: 'default',
}

const LESSON_LABEL: Record<ProgressLesson['state'], string> = {
  done: 'Done',
  awaiting_review: 'Waiting for marks',
  next: 'Up next',
  not_started: 'Not started',
}

/** The side panel on My progress and on a learner's page: every course the person is on with
 * how far they are (finished ones included), then the chosen course's modules, each folding open
 * to its lessons. Only the module under way starts open, so a long course stays a short list. */
export function ProgressOutline({
  label,
  courses,
  selected,
  courseHref,
  lessonHref,
  anchors,
}: Props) {
  const [open, setOpen] = useState(false)
  const done = selected.modules.filter((m) => m.state === 'done').length

  return (
    <nav className={styles.panel} aria-label={label}>
      <button
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span>
          Courses and modules
          <span className={styles.toggleSub}>{selected.title}</span>
        </span>
        <Icon name={open ? 'chevronDown' : 'chevronRight'} size={14} />
      </button>

      <div className={`${styles.body} ${open ? styles.bodyOpen : ''}`}>
        <h2 className={styles.heading}>{courses.length === 1 ? 'Course' : 'Courses'}</h2>
        <ul className={styles.courses}>
          {courses.map((c) => {
            const current = c.course_id === selected.course_id
            const complete = c.lessons_total > 0 && c.lessons_done === c.lessons_total
            const fresh = c.lessons_done === 0 && c.lessons_awaiting_review === 0
            return (
              <li key={c.course_id}>
                <Link
                  to={courseHref(c.course_id)}
                  className={`${styles.course} ${current ? styles.courseCurrent : ''}`}
                  aria-current={current ? 'page' : undefined}
                  onClick={() => setOpen(false)}
                >
                  <span className={styles.courseTitle}>{c.title}</span>
                  {complete ? (
                    <span className={`${styles.courseMeta} ${styles.complete}`}>
                      <Icon name="check" size={12} strokeWidth={2} /> Complete ·{' '}
                      {pluralize(c.lessons_total, 'lesson')}
                    </span>
                  ) : fresh ? (
                    <span className={styles.courseMeta}>
                      Not started · {pluralize(c.lessons_total, 'lesson')}
                    </span>
                  ) : (
                    <>
                      <span className={styles.courseMeta}>
                        {c.lessons_done} of {pluralize(c.lessons_total, 'lesson')}
                      </span>
                      <ProgressBar
                        value={c.lessons_done}
                        max={c.lessons_total}
                        label={`${c.title} progress`}
                      />
                    </>
                  )}
                </Link>
              </li>
            )
          })}
        </ul>

        {selected.modules.length > 0 && (
          <>
            <h2 className={styles.heading}>
              Modules
              <span className={styles.count}>
                {done} of {selected.modules.length} complete
              </span>
            </h2>
            <ol className={styles.modules} aria-label={`Modules in ${selected.title}`}>
              {selected.modules.map((m, i) => (
                <li key={m.id} className={`${styles.module} ${styles[`m_${m.state}`]}`}>
                  <details open={m.state === 'in_progress' || m.next_lesson !== null || undefined}>
                    <summary className={styles.summary}>
                      <ModuleMarker number={i + 1} state={MARKER[m.state]} size="sm" />
                      <span className={styles.moduleText}>
                        <span className={styles.moduleTitle}>{m.title}</span>
                        <span className={styles.moduleMeta}>
                          {m.state === 'done' ? (
                            <>Complete · {pluralize(m.lessons_total, 'lesson')}</>
                          ) : m.state === 'not_started' ? (
                            <>Not started · {pluralize(m.lessons_total, 'lesson')}</>
                          ) : (
                            <>
                              {m.lessons_done} of {pluralize(m.lessons_total, 'lesson')} done
                              {m.lessons_awaiting_review > 0 &&
                                ` · ${m.lessons_awaiting_review} waiting for marks`}
                            </>
                          )}
                        </span>
                      </span>
                      <Icon name="chevronDown" size={12} className={styles.chevron} />
                    </summary>
                    <ol className={styles.lessons} aria-label={`Lessons in ${m.title}`}>
                      {m.lessons.map((l) => {
                        const href = lessonHref(l.id)
                        return (
                          <li key={l.id} className={`${styles.lesson} ${styles[`l_${l.state}`]}`}>
                            <LessonDot state={l.state} />
                            <span className={styles.lessonText}>
                              {href ? (
                                <Go to={href} anchor={anchors}>
                                  {l.title}
                                </Go>
                              ) : (
                                l.title
                              )}
                              {(l.state === 'awaiting_review' || !l.required) && (
                                <span className={styles.lessonMeta}>
                                  {[
                                    l.state === 'awaiting_review' && 'Waiting for marks',
                                    !l.required && 'Optional',
                                  ]
                                    .filter(Boolean)
                                    .join(' · ')}
                                </span>
                              )}
                            </span>
                          </li>
                        )
                      })}
                    </ol>
                  </details>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </nav>
  )
}

/** The two-column page: the side panel, then the chosen course. On a narrow container (a phone,
 * or the admin console beside its own menu) the panel folds into a button above the course. */
export function OutlineLayout({ panel, children }: { panel: ReactNode; children: ReactNode }) {
  return (
    <div className={styles.layout}>
      <div className={styles.grid}>
        <aside className={styles.aside}>{panel}</aside>
        <div className={styles.main}>{children}</div>
      </div>
    </div>
  )
}

/** Status is a shape and a word (for screen readers), never colour alone. */
function LessonDot({ state }: { state: ProgressLesson['state'] }) {
  return (
    <span className={`${styles.dot} ${styles[`dot_${state}`]}`}>
      {state === 'done' && <Icon name="check" size={10} strokeWidth={2.25} />}
      {state === 'awaiting_review' && <Icon name="clock" size={10} strokeWidth={1.75} />}
      {state === 'next' && <Icon name="arrowRight" size={9} strokeWidth={2} />}
      <span className="sr-only">{LESSON_LABEL[state]}</span>
    </span>
  )
}
