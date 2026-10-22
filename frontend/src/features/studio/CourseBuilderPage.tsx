import { Link, NavLink, Outlet, useParams } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { PageState } from '../../components/PageState'
import { useAsync } from '../catalog/useAsync'
import type { BuilderContext } from './builderContext'
import styles from './CourseBuilderPage.module.css'
import { PublishPanel } from './PublishPanel'
import { readiness } from './readiness'
import { ReadinessControl } from './ReadinessControl'
import { StageStepper } from './StageStepper'
import { StatusChip } from './StatusChip'
import { studioApi } from './studioApi'
import { useCourseDetail } from './useCourseDetail'

const TABS = [
  { to: 'curriculum', label: 'Curriculum' },
  { to: 'overview', label: 'Overview' },
  { to: 'import', label: 'Import' },
  { to: 'settings', label: 'Settings' },
]

/** One course, edited as "this course" — never as versions or node ids.
 * The course bar carries the whole journey: where it is (stepper), what's
 * left (readiness), and the next move (Preview → Submit → Publish). */
export function CourseBuilderPage() {
  const { courseId = '' } = useParams()
  const detail = useCourseDetail(courseId)
  const types = useAsync(() => studioApi.activityTypes(), 'activity-types')

  if (detail.loading || types.loading) return <PageState kind="loading" />
  if (detail.notFound) {
    return (
      <PageState kind="empty" title="Course not found">
        <Link to="/studio">Back to courses</Link>
      </PageState>
    )
  }
  if (detail.error || !detail.course || !types.data) {
    return (
      <PageState kind="error" title="Couldn’t load this course" onRetry={detail.reload}>
        {detail.error ?? types.error}
      </PageState>
    )
  }

  const { course } = detail
  const context: BuilderContext = { ...detail, course, activityTypes: types.data }
  const root = course.tree?.root ?? null
  const issues = readiness(root)

  return (
    <div className={styles.page}>
      <header className={styles.bar}>
        <div className={styles.top}>
          <div className={styles.identity}>
            <Link to="/studio" className={styles.back}>
              <Icon name="arrowLeft" size={14} /> Courses
            </Link>
            <div className={styles.titleRow}>
              <h1>{course.title}</h1>
              <StatusChip status={course.status} />
            </div>
          </div>
          <div className={styles.actions}>
            {course.editable && <ReadinessControl courseId={course.id} issues={issues} />}
            {root && (
              <Link to={`/studio/courses/${course.id}/preview`} className="btn">
                <Icon name="eye" size={16} /> Preview
              </Link>
            )}
            <PublishPanel course={course} apply={detail.apply} />
          </div>
        </div>
        <div className={styles.sub}>
          <nav className={styles.tabs} aria-label="Course sections">
            {TABS.map((tab) => (
              <NavLink
                key={tab.to}
                to={tab.to}
                className={({ isActive }) => `${styles.tab} ${isActive ? styles.active : ''}`}
              >
                {tab.label}
              </NavLink>
            ))}
          </nav>
          <div className={styles.stepper}>
            <StageStepper status={course.status} />
          </div>
        </div>
      </header>
      <Outlet context={context} />
    </div>
  )
}
