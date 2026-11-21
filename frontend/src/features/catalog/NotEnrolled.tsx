import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { useCan, useCanAny } from '../../lib/capabilities'
import { CAN } from '../../lib/capabilityKeys'
import styles from './NotEnrolled.module.css'

/** What My courses and My progress show to someone on no course. A learner learns what happens
 * next; staff (who are often on no course) get a way to the work they came for. */
export function NotEnrolled({ what }: { what: 'courses' | 'progress' }) {
  const canAuthor = useCan(CAN.authorContent)
  const canAdmin = useCanAny([
    CAN.viewResults,
    CAN.viewAudit,
    CAN.manageUsers,
    CAN.manageRoles,
    CAN.rateSimulations,
    CAN.manageReviews,
  ])
  const staff = canAuthor || canAdmin

  return (
    <div className={styles.wrap}>
      <section className={styles.card} aria-labelledby="not-enrolled">
        <span className={styles.icon} aria-hidden="true">
          <Icon name="book" size={22} />
        </span>
        <h1 id="not-enrolled" className={styles.title}>
          You aren’t enrolled in a course yet
        </h1>
        <p className={styles.body}>
          {staff
            ? `Courses you’re enrolled on as a learner appear here. Staff work lives in ${
                canAuthor && canAdmin ? 'Studio and Admin' : canAuthor ? 'Studio' : 'Admin'
              }.`
            : `Your trainer enrolls you. When they do, you’ll get a notification and your ${
                what === 'courses' ? 'courses' : 'progress'
              } will show up here.`}
        </p>
        {staff && (
          <div className={styles.actions}>
            {canAdmin && (
              <Link to="/admin" className="btn btn-primary">
                Go to Admin
              </Link>
            )}
            {canAuthor && (
              <Link to="/studio" className={`btn ${canAdmin ? '' : 'btn-primary'}`}>
                Open Studio
              </Link>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
