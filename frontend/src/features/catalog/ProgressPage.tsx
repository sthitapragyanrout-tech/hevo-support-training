import { Link, useSearchParams } from 'react-router-dom'

import { PageState } from '../../components/PageState'
import { ProgressBar } from '../../components/ProgressBar'
import { progressApi, type ProgressCourse } from '../../lib/api'
import { percent, shortDate } from './activities/quizTypes'
import { OutlineLayout, ProgressOutline } from './ProgressOutline'
import { ProgressScores } from './ProgressScores'
import styles from './ProgressPage.module.css'
import { pluralize } from './treeUtils'
import { useAsync } from './useAsync'

/** Your own results across the courses you are enrolled on: just the facts the platform records
 * about you. There is deliberately no overall score, pass/fail for a course or ranking here. */
export function ProgressPage() {
  const { data, loading, error, reload } = useAsync(() => progressApi.summary(), 'progress-summary')
  const [params] = useSearchParams()

  if (loading) return <PageState kind="loading" />
  if (error || !data) {
    return (
      <PageState kind="error" title="Couldn’t load your progress" onRetry={reload}>
        {error}
      </PageState>
    )
  }
  if (data.courses.length === 0) {
    return (
      <PageState kind="empty" title="You aren’t enrolled in a course yet">
        Ask your trainer to enroll you. Your progress will appear here.
      </PageState>
    )
  }

  // The course picked in the side panel (kept in the URL); else the one under way, else the
  // first one not finished.
  const chosen = Number(params.get('course'))
  const selected =
    data.courses.find((c) => c.course_id === chosen) ??
    data.courses.find((c) => c.lessons_done > 0 && c.lessons_done < c.lessons_total) ??
    data.courses.find((c) => c.lessons_done < c.lessons_total) ??
    data.courses[0]
  const done = data.courses.reduce((n, c) => n + c.lessons_done, 0)
  const total = data.courses.reduce((n, c) => n + c.lessons_total, 0)
  const waiting = data.courses.reduce((n, c) => n + c.lessons_awaiting_review, 0)

  return (
    <div>
      <header className={`ink band ${styles.hero}`}>
        <div className={`page ${styles.heroInner}`}>
          <div className={styles.header}>
            <p className="eyebrow">Learning</p>
            <h1 className={styles.heading}>My progress</h1>
            <p className={styles.lede}>Where you are on each course, and how your work has gone.</p>
          </div>
          <dl className={styles.summary}>
            <div>
              <dt>Lessons complete</dt>
              <dd>
                <span className="num">{done}</span>
                <small>of {total}</small>
              </dd>
            </div>
            <div>
              <dt>Courses</dt>
              <dd>
                <span className="num">{data.courses.length}</span>
              </dd>
            </div>
            {waiting > 0 && (
              <div>
                <dt>Waiting for marks</dt>
                <dd>
                  <span className="num">{waiting}</span>
                </dd>
              </div>
            )}
          </dl>
        </div>
      </header>
      <div className={`page ${styles.body}`}>
        <OutlineLayout
          panel={
            <ProgressOutline
              label="Your courses"
              courses={data.courses}
              selected={selected}
              courseHref={(id) => `/progress?course=${id}`}
              lessonHref={(id) => `/courses/${selected.course_id}/lessons/${id}`}
            />
          }
        >
          <CourseSection key={selected.version_id} course={selected} />
        </OutlineLayout>
      </div>
    </div>
  )
}

function CourseSection({ course }: { course: ProgressCourse }) {
  const base = `/courses/${course.course_id}`
  const lessonLink = (id: number) => `${base}/lessons/${id}`
  const complete = course.lessons_total > 0 && course.lessons_done === course.lessons_total
  const headingId = `course-${course.version_id}`
  const fresh =
    course.lessons_total === 0 ||
    (course.lessons_done === 0 && course.lessons_awaiting_review === 0)

  return (
    <section className={styles.course} aria-labelledby={headingId}>
      <div className={styles.courseHead}>
        <h2 id={headingId} className={styles.courseTitle}>
          <Link to={base}>{course.title}</Link>
        </h2>
        {!fresh && (
          <span className={`num ${styles.pct}`} aria-hidden="true">
            {Math.round((course.lessons_done / course.lessons_total) * 100)}
            <small>%</small>
          </span>
        )}
      </div>
      <div className={styles.overview}>
        {fresh ? (
          // Nothing done yet reads as words, never as 0% and an empty bar.
          <p className={styles.counts}>Not started · {pluralize(course.lessons_total, 'lesson')}</p>
        ) : (
          <>
            <ProgressBar
              value={course.lessons_done}
              max={course.lessons_total}
              label={`${course.title} progress`}
            />
            <p className={styles.counts}>
              {course.lessons_done} of {pluralize(course.lessons_total, 'lesson')} complete
              {course.lessons_awaiting_review > 0 &&
                ` · ${course.lessons_awaiting_review} waiting for marks or a rating`}
            </p>
          </>
        )}
        <p className={styles.next}>
          {complete ? (
            'All lessons complete.'
          ) : course.next_lesson ? (
            <>
              Next: <Link to={lessonLink(course.next_lesson.id)}>{course.next_lesson.title}</Link>
            </>
          ) : (
            'Nothing left to start right now.'
          )}
        </p>
      </div>

      <CertificateLine course={course} />

      <ProgressScores course={course} hrefOf={(item) => lessonLink(item.lesson_id)} />
    </section>
  )
}

const KIND = { quiz: 'quizzes', practice: 'practice tickets', rated: 'mentor-rated work' }

/** The course's certificate, when it has one: earned (with a link), or the course score so far
 * against what is needed, and what is still missing. Nothing at all when it isn't switched on. */
function CertificateLine({ course }: { course: ProgressCourse }) {
  const c = course.certification
  if (c.certificate) {
    return (
      <p className={`${styles.cert} ${styles.certEarned}`}>
        <strong>Certificate earned</strong> on {shortDate(c.certificate.issued_at)} ·{' '}
        <Link to={`/certificates/${c.certificate.code}`}>View certificate</Link>
      </p>
    )
  }
  if (!c.enabled) return null
  const left = course.lessons_total - course.lessons_done
  return (
    <p className={styles.cert}>
      <strong>Certificate</strong>
      {' · '}
      {c.score === null
        ? `pass mark ${c.threshold}%`
        : `course score so far ${percent(c.score)} · pass mark ${c.threshold}%`}
      {left > 0 && ` · finish the course to earn it`}
      {c.missing.length > 0 && ` · still to do: ${c.missing.map((k) => KIND[k]).join(', ')}`}
    </p>
  )
}
