import { useEffect, useMemo, useState } from 'react'
import { Link, Navigate, useLocation, useParams } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { PageState } from '../../components/PageState'
import { ActivityList } from './ActivityList'
import { useCourse } from './courseContext'
import { LessonContent } from './LessonContent'
import { extractOutline, type OutlineItem } from './lesson/outline'
import { LessonOutline } from './lesson/LessonOutline'
import styles from './LessonPage.module.css'
import { LockedLesson } from './LockedLesson'
import { ModuleMarker } from './ModuleMarker'
import {
  formatMinutes,
  lessonMinutes,
  lessonNeighbors,
  pendingRequired,
  resolveLessonTarget,
  summarize,
} from './treeUtils'

export function LessonPage() {
  const { nodeId = '' } = useParams()
  const { hash } = useLocation()
  const { basePath, root, modules, lessons, progress, preview } = useCourse()
  const [busy, setBusy] = useState(false)

  const id = Number(nodeId)
  const lesson = lessons.find((l) => l.node.id === id)

  // "In this lesson": the sections if there are any, else the intro's own headings.
  const outline = useMemo<OutlineItem[]>(() => {
    if (!lesson) return []
    return lesson.sections.length > 0
      ? lesson.sections.map((s) => ({ id: `section-${s.id}`, text: s.title }))
      : extractOutline(lesson.node.description)
  }, [lesson])

  useEffect(() => {
    if (!lesson) return
    document.title = `${lesson.node.title} · Hevo Support Training`
    const target = hash ? document.getElementById(hash.slice(1)) : null
    if (target) target.scrollIntoView?.()
    else document.documentElement.scrollTop = 0 // jsdom-safe: no scrollTo
    return () => {
      document.title = 'Hevo Support Training Platform'
    }
  }, [lesson?.node.id, lesson?.node.title, hash])

  if (!lesson) {
    // A module or section id: send the learner to the lesson that holds it.
    const target = resolveLessonTarget(modules, id)
    if (target) {
      const anchor = target.sectionId ? `#section-${target.sectionId}` : ''
      return <Navigate to={`${basePath}/lessons/${target.lessonId}${anchor}`} replace />
    }
    return (
      <PageState kind="empty" title="Lesson not found">
        This lesson isn’t part of the course. <Link to={basePath}>Back to the course</Link>
      </PageState>
    )
  }

  const { node, sections } = lesson
  const module = modules.find((m) => m.node.id === lesson.moduleId)!
  const indexInModule = module.lessons.findIndex((l) => l.node.id === id) + 1
  const { previous, next } = lessonNeighbors(lessons, id)
  const minutesValue = lessonMinutes(lesson)
  const minutes = minutesValue != null ? formatMinutes(minutesValue) : null
  const nextMinutes = next ? lessonMinutes(next) : null
  const meta = [
    `Lesson ${indexInModule} of ${module.lessons.length}`,
    minutes,
    node.is_required ? 'Required' : 'Optional',
  ].filter(Boolean)
  const startsNewModule = next != null && next.moduleId !== lesson.moduleId
  const empty =
    !node.description.trim() && sections.length === 0 && node.activities.length === 0

  const done = progress.completed.has(node.id)
  const awaiting = progress.awaiting.has(node.id)
  const pending = pendingRequired(lesson, progress.activities, progress.rated)
  const canRecord = progress.available && !preview
  const canComplete = canRecord && pending.length === 0
  const reason = preview
    ? 'Progress isn’t recorded in preview.'
    : !progress.available
      ? 'Loading your progress…'
      : pending.length > 0
        ? `Finish the ${pending.length} required ${pending.length === 1 ? 'activity' : 'activities'} above first.`
        : null

  const lock = done || awaiting ? null : progress.lockOf(node.id)
  const blocker = lock ? lessons.find((l) => l.node.id === lock.blockedBy) : null
  const nextLock = next && !progress.completed.has(next.node.id) ? progress.lockOf(next.node.id) : null

  const crumbs = (
    <nav aria-label="Breadcrumb" className={styles.breadcrumb}>
      <Link to={basePath} className={styles.course}>
        {root.title}
      </Link>
      <Icon name="chevronRight" size={12} />
      <span className={styles.module}>
        <ModuleMarker number={lesson.moduleNumber} state="current" size="sm" />{' '}
        <span>{module.node.title}</span>
      </span>
    </nav>
  )

  // A lesson that isn't open yet shows why instead of its content, and mounts
  // nothing that could record progress.
  if (lock) {
    return (
      <div className={styles.page}>
        <article className={styles.lesson}>
          {crumbs}
          <header className={styles.header}>
            <h1>{node.title}</h1>
            <p className={styles.meta}>
              <span>Locked</span>
              <span>{node.is_required ? 'Required' : 'Optional'}</span>
            </p>
          </header>
          <LockedLesson
            basePath={basePath}
            blockedBy={{ id: lock.blockedBy, title: blocker?.node.title ?? lock.title }}
          />
        </article>
      </div>
    )
  }

  async function run(task: () => Promise<void>) {
    setBusy(true)
    try {
      await task()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.page}>
      <article className={styles.lesson}>
        {crumbs}

        <header className={styles.header}>
          <h1>{node.title}</h1>
          <p className={styles.meta}>
            {meta.map((m, i) => (
              <span key={i}>{m}</span>
            ))}
          </p>
        </header>

        <LessonContent markdown={node.description} />

        {sections.map((section) => (
          <section
            key={section.id}
            id={`section-${section.id}`}
            className={styles.section}
            aria-labelledby={`section-${section.id}-title`}
          >
            <h2 id={`section-${section.id}-title`} className={styles.sectionTitle}>
              {section.title}
            </h2>
            <LessonContent markdown={section.description} lead={false} />
            {section.activities.length > 0 && (
              <div className={styles.practice}>
                <h3>Put it into practice</h3>
                <ActivityList activities={section.activities} />
              </div>
            )}
          </section>
        ))}

        {node.activities.length > 0 && (
          <section className={styles.activities} aria-labelledby="activities-heading">
            <h2 id="activities-heading">
              {sections.length > 0 ? 'To finish the lesson' : 'Then put it into practice'}
            </h2>
            <ActivityList activities={node.activities} />
          </section>
        )}

        {empty && <p className={styles.empty}>This lesson has no content yet.</p>}

        <footer className={styles.footer}>
          <div className={styles.complete}>
            {awaiting ? (
              <p className={styles.hint}>
                You can move on. This lesson is complete once your mentor passes your simulation.
              </p>
            ) : done ? (
              <>
                <span className={styles.completed}>
                  <Icon name="check" size={16} strokeWidth={2.2} /> Lesson complete
                </span>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={busy}
                  onClick={() => void run(() => progress.uncompleteLesson(node.id))}
                >
                  Mark incomplete
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busy || !canComplete}
                  onClick={() => void run(() => progress.completeLesson(node.id))}
                >
                  Mark complete
                </button>
                {reason && <span className={styles.hint}>{reason}</span>}
              </>
            )}
          </div>
          {progress.error && (
            <p role="alert" className={styles.problem}>
              {progress.error}
            </p>
          )}

          {next ? (
            <Link to={`${basePath}/lessons/${next.node.id}`} className={styles.upNext}>
              <span className={styles.upNextLabel}>
                Up next{startsNewModule && ` · Module ${String(next.moduleNumber).padStart(2, '0')}`}
                {nextLock && ' · Locked'}
              </span>
              <span className={styles.upNextTitle}>{next.node.title}</span>
              <span className={styles.upNextSummary}>
                {nextLock
                  ? `Unlocks when you complete “${nextLock.title}”.`
                  : summarize(next.node.description, 170)}
                {!nextLock && nextMinutes != null && (
                  <span className={styles.upNextTime}> · {formatMinutes(nextMinutes)}</span>
                )}
              </span>
              <span className={styles.upNextArrow} aria-hidden="true">
                <Icon name="arrowRight" size={20} />
              </span>
            </Link>
          ) : (
            <div className={styles.end}>
              <p className={styles.upNextLabel}>You’ve reached the end</p>
              <Link to={basePath} className={styles.endLink}>
                Return to the course overview <Icon name="arrowRight" size={16} />
              </Link>
            </div>
          )}

          {previous && (
            <Link to={`${basePath}/lessons/${previous.node.id}`} className={styles.previous}>
              <Icon name="arrowLeft" size={14} />
              <span>
                Previous lesson: <span className={styles.previousTitle}>{previous.node.title}</span>
              </span>
            </Link>
          )}
        </footer>
      </article>

      <aside className={styles.rail}>
        <LessonOutline items={outline} minutes={minutes} />
      </aside>
    </div>
  )
}
