import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { ProgressBar } from '../../components/ProgressBar'
import type { LessonStatus } from '../../components/StatusIcon'
import { activityMix } from './activityTypes'
import { useCourse } from './courseContext'
import { parseCourseIntro } from './courseIntro'
import styles from './CourseLandingPage.module.css'
import { lessonStatus, moduleMarker, unlockHint } from './lessonState'
import { ModuleSection } from './ModuleSection'
import {
  firstIncompleteLesson,
  formatMinutes,
  lessonMinutes,
  pluralize,
  searchLessons,
  totalMinutes,
  type Lesson,
} from './treeUtils'
import { hasStarted } from './useProgress'

export function CourseLandingPage() {
  const { basePath, root, modules, lessons, progress } = useCourse()
  const [query, setQuery] = useState('')

  useEffect(() => {
    document.title = `${root.title} · Hevo Support Training`
    return () => {
      document.title = 'Hevo Support Training Platform'
    }
  }, [root.title])

  const started = hasStarted(progress)
  const doneCount = lessons.filter((l) => progress.completed.has(l.node.id)).length
  const allDone = lessons.length > 0 && doneCount === lessons.length
  const minutes = totalMinutes(lessons)
  const serverNext = lessons.find((l) => l.node.id === progress.nextLessonId)
  const target =
    (started ? (serverNext ?? firstIncompleteLesson(lessons, progress.completed)) : null) ??
    serverNext ??
    lessons[0]
  const targetMinutes = target ? lessonMinutes(target) : null
  const { lead, outcomes } = parseCourseIntro(root.description)
  const mix = activityMix(lessons)

  const statusText = allDone
    ? 'Completed'
    : started
      ? `${doneCount} of ${pluralize(lessons.length, 'lesson')} completed`
      : 'Not started'
  const duration = minutes != null ? `~${formatMinutes(minutes)}` : null
  // One quiet line for small screens (the "At a glance" column is desktop-only).
  const metaLine = [
    started ? statusText : `Not started · ${pluralize(lessons.length, 'lesson')}`,
    pluralize(modules.length, 'module'),
    duration,
  ]
    .filter(Boolean)
    .join(' · ')

  const matches = new Set(searchLessons(modules, query).map((l) => l.node.id))
  const filtering = query.trim().length > 0
  const visible = modules
    .map((m) => ({ module: m, lessons: m.lessons.filter((l) => matches.has(l.node.id)) }))
    .filter((m) => !filtering || m.lessons.length > 0)

  const statusOf = (lesson: Lesson): LessonStatus => lessonStatus(lesson, progress)

  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div className={styles.intro}>
          <p className={styles.eyebrow}>Onboarding course</p>
          <h1>{root.title}</h1>
          {lead.map((p, i) => (
            <p key={i} className={i === 0 ? styles.lead : styles.more}>
              {p}
            </p>
          ))}
          <p className={styles.metaLine}>{metaLine}</p>

          {started && (
            <div className={styles.progress}>
              <ProgressBar value={doneCount} max={lessons.length} label="Course progress" />
            </div>
          )}

          {target ? (
            <div className={styles.start}>
              <Link
                to={`${basePath}/lessons/${target.node.id}`}
                className={`btn btn-primary ${styles.cta}`}
              >
                {allDone ? 'Review course' : started ? 'Continue learning' : 'Start course'}
                <Icon name="arrowRight" size={16} />
              </Link>
              <p className={styles.startsWith}>
                {allDone ? (
                  'You’ve completed every lesson. Revisit any of them below.'
                ) : (
                  <>
                    {started ? 'Up next: ' : 'Starts with '}
                    <strong>{target.node.title}</strong>
                    {targetMinutes != null && ` · ${formatMinutes(targetMinutes)}`}
                  </>
                )}
              </p>
            </div>
          ) : (
            <p className={styles.more}>No lessons have been added yet.</p>
          )}
        </div>

        <section className={styles.glance} aria-label="At a glance">
          <dl>
          <div>
            <dt>Status</dt>
            <dd>{statusText}</dd>
          </div>
          {duration && (
            <div>
              <dt>Time</dt>
              <dd>{duration}</dd>
            </div>
          )}
          <div>
            <dt>Lessons</dt>
            <dd>{`${lessons.length} in ${pluralize(modules.length, 'module')}`}</dd>
          </div>
          {mix.length > 0 && (
            <div>
              <dt>Includes</dt>
              <dd>{mix.join(', ')}</dd>
            </div>
          )}
          </dl>
        </section>
      </header>

      {outcomes.length > 0 && (
        <section className={styles.outcomes} aria-labelledby="outcomes-heading">
          <h2 id="outcomes-heading" className={styles.sectionHeading}>
            What you’ll learn
          </h2>
          <ul className={styles.outcomeList}>
            {outcomes.map((o) => (
              <li key={o}>
                <Icon name="target" size={16} />
                {o}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="curriculum-heading" className={styles.curriculum}>
        <div className={styles.curriculumHead}>
          <h2 id="curriculum-heading" className={styles.sectionHeading}>
            Your path through the course
          </h2>
          {lessons.length > 0 && (
            <input
              type="search"
              className={styles.filter}
              placeholder="Filter lessons"
              aria-label="Filter lessons"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          )}
        </div>

        {visible.length === 0 ? (
          <p className={styles.empty}>
            {filtering ? `No lessons match “${query.trim()}”.` : 'This course has no modules yet.'}
          </p>
        ) : (
          <div>
            {visible.map(({ module, lessons: shown }) => (
              <ModuleSection
                key={module.node.id}
                basePath={basePath}
                module={module}
                lessons={shown}
                statusOf={statusOf}
                lockedHintOf={(lesson) => unlockHint(lesson, progress)}
                markerState={moduleMarker(module, progress, target?.moduleId ?? null)}
                variant="detailed"
              />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
