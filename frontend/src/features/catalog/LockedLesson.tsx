import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import styles from './LockedLesson.module.css'

interface Props {
  basePath: string
  /** The lesson to finish first. */
  blockedBy: { id: number; title: string }
}

/** What a learner sees on a lesson that isn't open yet: why, and the one thing
 * to do about it. Nothing here can record progress. */
export function LockedLesson({ basePath, blockedBy }: Props) {
  return (
    <section className={styles.locked} aria-labelledby="locked-title">
      <span className={styles.badge} aria-hidden="true">
        <Icon name="lock" size={18} strokeWidth={1.75} />
      </span>
      <div>
        <h2 id="locked-title">This lesson isn’t open yet</h2>
        <p>
          It unlocks when you complete <strong>{blockedBy.title}</strong>. Courses like this one go in
          order, so each lesson builds on the one before.
        </p>
        <Link to={`${basePath}/lessons/${blockedBy.id}`} className="btn btn-primary">
          Go to {blockedBy.title} <Icon name="arrowRight" size={16} />
        </Link>
      </div>
    </section>
  )
}
