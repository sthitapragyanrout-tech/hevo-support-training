import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { PageState } from '../../components/PageState'
import { useCan } from '../../lib/capabilities'
import { CAN } from '../../lib/capabilityKeys'
import { useAsync } from '../catalog/useAsync'
import { StatusChip } from './StatusChip'
import styles from './StudioCourseList.module.css'
import { studioApi } from './studioApi'
import type { AuthCourseSummary } from './types'

interface Group {
  key: string
  title: string
  hint?: string
  courses: AuthCourseSummary[]
}

function meta(course: AuthCourseSummary): string {
  const { modules = 0, lessons = 0 } = course
  if (modules === 0) return 'No content yet'
  return `${modules} module${modules === 1 ? '' : 's'} · ${lessons} lesson${lessons === 1 ? '' : 's'}`
}

export function StudioCourseList() {
  const { data, loading, error, reload } = useAsync(() => studioApi.courses(), 'studio-courses')
  const canPublish = useCan(CAN.publishCourse)

  if (loading) return <PageState kind="loading" />
  if (error || !data) {
    return (
      <PageState kind="error" title="Couldn’t load your courses" onRetry={reload}>
        {error}
      </PageState>
    )
  }

  // Group by what the person has to do next, not by when it was made.
  const review = data.filter((c) => c.status.key === 'in_review')
  const progress = data.filter((c) => ['draft', 'published_with_draft'].includes(c.status.key))
  const live = data.filter((c) => c.status.key === 'published')
  const groups: Group[] = [
    {
      key: 'review',
      title: canPublish ? 'Waiting to be published' : 'With an administrator',
      hint: canPublish ? 'Review, then publish or send back.' : 'Submitted — you’ll see it here once it’s live.',
      courses: review,
    },
    { key: 'progress', title: 'In progress', courses: progress },
    { key: 'live', title: 'Published', courses: live },
  ].filter((g) => g.courses.length > 0)

  function action(course: AuthCourseSummary): string {
    if (course.status.key === 'in_review') return canPublish ? 'Review' : 'View'
    if (course.status.key === 'published') return 'Open'
    return 'Continue'
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className="eyebrow">Studio</p>
          <h1>Courses</h1>
        </div>
        <Link to="/studio/new" className="btn btn-primary">
          <Icon name="plus" size={16} /> Create course
        </Link>
      </header>

      {groups.length === 0 ? (
        <div className={styles.empty}>
          <h2>Build your first course</h2>
          <p>
            Create a course, add modules and lessons, then preview it as a learner would see it. Have
            a plan in a spreadsheet? Import it once the course exists.
          </p>
          <Link to="/studio/new" className="btn btn-primary">
            Create course
          </Link>
        </div>
      ) : (
        groups.map((group) => (
          <section key={group.key} className={styles.group} aria-labelledby={`g-${group.key}`}>
            <div className={styles.groupHead}>
              <h2 id={`g-${group.key}`}>{group.title}</h2>
              <span className={styles.count}>{group.courses.length}</span>
              {group.hint && <span className={styles.hint}>{group.hint}</span>}
            </div>
            <ul className={styles.list}>
              {group.courses.map((course) => (
                <li key={course.id}>
                  <Link to={`/studio/courses/${course.id}`} className={styles.row}>
                    <span className={styles.main}>
                      <span className={styles.title}>{course.title}</span>
                      <span className={styles.meta}>{meta(course)}</span>
                    </span>
                    <StatusChip status={course.status} />
                    <span className={styles.action}>
                      {action(course)} <Icon name="arrowRight" size={14} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  )
}
