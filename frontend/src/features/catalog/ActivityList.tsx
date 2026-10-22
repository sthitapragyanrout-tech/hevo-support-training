import type { ActivitySummary } from '../../lib/api'
import { ActivityRunner } from './activities/ActivityRunner'
import styles from './ActivityList.module.css'

/** What a learner does in this lesson or section — each activity rendered by
 * its own type, in one consistent frame. */
export function ActivityList({ activities }: { activities: ActivitySummary[] }) {
  return (
    <ol className={styles.list}>
      {activities.map((activity) => (
        <li key={activity.id} className={styles.item}>
          <ActivityRunner activity={activity} />
        </li>
      ))}
    </ol>
  )
}
