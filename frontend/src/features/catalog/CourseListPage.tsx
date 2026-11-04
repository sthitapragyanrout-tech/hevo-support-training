import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { PageState } from '../../components/PageState'
import { catalogApi, progressApi } from '../../lib/api'
import { parseCourseIntro } from './courseIntro'
import styles from './CourseListPage.module.css'
import { flattenLessons, formatMinutes, getModules, pluralize, totalMinutes } from './treeUtils'
import { useAsync } from './useAsync'

/** The list endpoint carries no counts, so each course's tree is fetched to
 * show lesson/duration meta. Fine for a small internal catalog; if it grows,
 * add the counts to the summary serializer instead. */
async function loadCourses() {
  const courses = await catalogApi.courses()
  return Promise.all(
    courses.map(async (course) => {
      const [tree, progress] = await Promise.all([
        catalogApi.course(course.id),
        progressApi.course(course.id),
      ])
      const modules = tree.root ? getModules(tree.root) : []
      const lessons = flattenLessons(modules)
      const done = new Set(progress.completed_lessons)
      return {
        course,
        modules: modules.length,
        lessons: lessons.length,
        minutes: totalMinutes(lessons),
        completed: lessons.filter((l) => done.has(l.node.id)).length,
        touched: Object.keys(progress.activities).length > 0,
        // What to do next, as the server sees it (open, unfinished, required first).
        next: lessons.find((l) => l.node.id === progress.next_lesson_id)?.node.title ?? null,
      }
    }),
  )
}

export function CourseListPage() {
  const { data, loading, error, reload } = useAsync(loadCourses, 'courses')

  if (loading) return <PageState kind="loading" />
  if (error || !data) {
    return (
      <PageState kind="error" title="Couldn’t load your courses" onRetry={reload}>
        {error}
      </PageState>
    )
  }
  if (data.length === 0) {
    return (
      <PageState kind="empty" title="No courses yet">
        Courses appear here once a trainer publishes them.
      </PageState>
    )
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <p className="eyebrow">Learning</p>
        <h1 className={styles.heading}>My courses</h1>
      </header>
      <ul className={styles.list}>
        {data.map(({ course, modules, lessons, minutes, completed, touched, next }) => {
          const complete = lessons > 0 && completed === lessons
          const inProgress = !complete && (completed > 0 || touched)
          const blurb = parseCourseIntro(course.description).lead[0]
          return (
            <li key={course.id}>
              <Link to={`/courses/${course.id}`} className={styles.row}>
                <span className={styles.marker} aria-hidden="true">
                  <Icon name="book" size={20} />
                </span>
                <div className={styles.text}>
                  <h2>{course.title}</h2>
                  {blurb && <p className={styles.description}>{blurb}</p>}
                  <p className={styles.meta}>
                    <span className={`${styles.state} ${complete ? styles.complete : ''}`}>
                      {complete
                        ? 'Completed'
                        : inProgress
                          ? `In progress · ${completed} of ${lessons} lessons`
                          : 'Not started'}
                    </span>
                    {!inProgress && !complete && <span>{pluralize(lessons, 'lesson')}</span>}
                    <span>{pluralize(modules, 'module')}</span>
                    {minutes != null && <span>~{formatMinutes(minutes)}</span>}
                  </p>
                  {inProgress && next && (
                    <p className={styles.next}>
                      Next: <span>{next}</span>
                    </p>
                  )}
                </div>
                <span className={styles.action}>
                  {complete ? 'Review' : inProgress ? 'Continue' : 'Start course'}{' '}
                  <Icon name="arrowRight" size={16} />
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
