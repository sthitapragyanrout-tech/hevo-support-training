import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { PageState } from '../../components/PageState'
import { ProgressBar } from '../../components/ProgressBar'
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
        // Minutes still ahead of them: what is left, not what the course adds up to.
        minutesLeft: totalMinutes(lessons.filter((l) => !done.has(l.node.id))),
        completed: lessons.filter((l) => done.has(l.node.id)).length,
        touched: Object.keys(progress.activities).length > 0,
        // What to do next, as the server sees it (open, unfinished, required first).
        next: lessons.find((l) => l.node.id === progress.next_lesson_id)?.node.title ?? null,
      }
    }),
  )
}

type Row = Awaited<ReturnType<typeof loadCourses>>[number]

const isComplete = (r: Row) => r.lessons > 0 && r.completed === r.lessons
const isStarted = (r: Row) => !isComplete(r) && (r.completed > 0 || r.touched)

/** The course to put first: the one they are furthest through, else the first they have not
 * started. Nothing is claimed about *when* they last worked on it: the data does not say. */
function pickFeatured(rows: Row[]): Row | null {
  const started = rows.filter(isStarted)
  if (started.length > 0) {
    return [...started].sort((a, b) => b.completed / b.lessons - a.completed / a.lessons)[0]
  }
  return rows.find((r) => !isComplete(r)) ?? null
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
      <PageState kind="empty" title="You aren’t enrolled in a course yet">
        Ask your trainer to enroll you. Your courses will appear here.
      </PageState>
    )
  }

  const featured = pickFeatured(data)
  const doneLessons = data.reduce((n, r) => n + r.completed, 0)
  const allLessons = data.reduce((n, r) => n + r.lessons, 0)
  const underway = data.filter(isStarted).length
  const finished = data.filter(isComplete).length
  const left = data.reduce((n, r) => n + (r.minutesLeft ?? 0), 0)
  const leftKnown = data.some((r) => r.minutesLeft != null)

  return (
    <div>
      <section className={`ink band ${styles.hero}`} aria-label="Your learning">
        <div className={`page ${styles.heroInner}`}>
          <div className={styles.heroMain}>
            <p className="eyebrow">Learning</p>
            <h1 className={styles.heading}>My courses</h1>
            {featured && (
              <div className={styles.featured}>
                <p className={styles.featuredLabel}>
                  {isStarted(featured) ? 'Up next for you' : 'Start here'}
                </p>
                <h2 className={styles.featuredTitle}>{featured.course.title}</h2>
                {isStarted(featured) && featured.next && (
                  <p className={styles.featuredNext}>
                    Next lesson <span>{featured.next}</span>
                  </p>
                )}
                {isStarted(featured) && (
                  <div className={styles.featuredBar}>
                    <ProgressBar
                      size="lg"
                      value={featured.completed}
                      max={featured.lessons}
                      label={`${featured.course.title} progress`}
                    />
                    <span>
                      {featured.completed} of {featured.lessons} lessons
                    </span>
                  </div>
                )}
                <Link to={`/courses/${featured.course.id}`} className="btn btn-signal btn-lg">
                  {isStarted(featured) ? 'Continue learning' : 'Start course'}
                  <Icon name="arrowRight" size={18} />
                </Link>
              </div>
            )}
            {!featured && (
              <p className={styles.caughtUp}>You’ve finished every course. Nicely done.</p>
            )}
          </div>

          <dl className={styles.stats}>
            <div>
              <dt>Lessons done</dt>
              <dd>
                <span className="num">{doneLessons}</span>
                <small>of {allLessons}</small>
              </dd>
            </div>
            <div>
              <dt>In progress</dt>
              <dd>
                <span className="num">{underway}</span>
                <small>
                  {finished > 0 ? `${finished} finished` : pluralize(data.length, 'course')}
                </small>
              </dd>
            </div>
            {leftKnown && (
              <div>
                <dt>Time left</dt>
                <dd>
                  <span className="num">{left > 0 ? formatMinutes(left) : '0 min'}</span>
                  <small>estimated</small>
                </dd>
              </div>
            )}
          </dl>
        </div>
      </section>

      <div className={`page ${styles.body}`}>
        <div className={styles.sectionHead}>
          <h2>All courses</h2>
          <p>{pluralize(data.length, 'course')}</p>
        </div>
        <ul className={styles.grid}>
          {data.map((row) => {
            const { course, modules, lessons, minutes, completed, next } = row
            const complete = isComplete(row)
            const inProgress = isStarted(row)
            const blurb = parseCourseIntro(course.description).lead[0]
            const pct = lessons > 0 ? Math.round((completed / lessons) * 100) : 0
            return (
              <li key={course.id}>
                <Link to={`/courses/${course.id}`} className={styles.tile}>
                  <div className={styles.tileTop}>
                    <span
                      className={`${styles.marker} ${complete ? styles.markerDone : ''}`}
                      aria-hidden="true"
                    >
                      <Icon name={complete ? 'check' : 'book'} size={20} />
                    </span>
                    {(inProgress || complete) && (
                      <span className={`num ${styles.pct}`}>
                        {pct}
                        <small>%</small>
                      </span>
                    )}
                  </div>
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
                  <div className={styles.tileFoot}>
                    {(inProgress || complete) && (
                      <ProgressBar
                        value={completed}
                        max={lessons}
                        label={`${course.title} progress`}
                      />
                    )}
                    <span className={styles.action}>
                      {complete ? 'Review' : inProgress ? 'Continue' : 'Start course'}{' '}
                      <Icon name="arrowRight" size={16} />
                    </span>
                  </div>
                </Link>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
