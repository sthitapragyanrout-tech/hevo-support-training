import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { progressApi } from '../../lib/api'
import { percent, shortDate } from './activities/quizTypes'
import styles from './CourseLandingPage.module.css'
import { useAsync } from './useAsync'

const KIND = { quiz: 'quizzes', practice: 'practice tickets', rated: 'mentor-rated work' }

/** A small card on the course overview: the certificate once it's earned (with a link to it), or
 * what earning it takes. It reads the same summary as My progress, so the two never disagree.
 * Nothing shows for a staff preview, a course without a certificate, or while it loads. */
export function CourseCertificate({ courseId }: { courseId: number }) {
  const { data } = useAsync(() => progressApi.summary(), `course-cert-${courseId}`)
  const course = data?.courses.find((c) => c.course_id === courseId)
  if (!course) return null
  const c = course.certification

  if (c.certificate) {
    return (
      <div className={`${styles.cert} ${styles.certEarned}`} role="status">
        <span className={styles.certIcon} aria-hidden="true">
          <Icon name="check" size={14} strokeWidth={2.25} />
        </span>
        <div className={styles.certText}>
          <strong>Certificate earned</strong>
          <span>
            {shortDate(c.certificate.issued_at)}
            {c.certificate.score != null && ` · course score ${percent(c.certificate.score)}`}
          </span>
        </div>
        <Link to={`/certificates/${c.certificate.code}`} className="btn btn-signal btn-sm">
          View certificate
        </Link>
      </div>
    )
  }

  if (!c.enabled) return null
  const left = course.lessons_total - course.lessons_done
  return (
    <div className={styles.cert}>
      <span className={styles.certIcon} aria-hidden="true">
        <Icon name="bookmark" size={14} />
      </span>
      <div className={styles.certText}>
        <strong>This course has a certificate</strong>
        <span>
          {left > 0
            ? `Finish every lesson with a course score of ${c.threshold}% or more`
            : `Needs a course score of ${c.threshold}% or more`}
          {c.score != null && ` · yours so far ${percent(c.score)}`}
          {c.missing.length > 0 && ` · still to do: ${c.missing.map((k) => KIND[k]).join(', ')}`}
        </span>
      </div>
    </div>
  )
}
