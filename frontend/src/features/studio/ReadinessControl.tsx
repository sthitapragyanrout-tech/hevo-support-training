import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { Popover } from '../../components/Popover'
import styles from './ReadinessControl.module.css'
import type { ReadinessIssue } from './readiness'

interface Props {
  courseId: number
  issues: ReadinessIssue[]
}

/** "Ready to submit" or "N to finish ▾" with the list. The honest answer to
 * "can I send this off yet?", kept in view while you work. */
export function ReadinessControl({ courseId, issues }: Props) {
  if (issues.length === 0) {
    return (
      <span className={styles.ready}>
        <Icon name="check" size={14} strokeWidth={2} /> Ready to submit
      </span>
    )
  }
  return (
    <Popover
      label="What’s left to finish"
      align="end"
      width={360}
      trigger={(props) => (
        <button type="button" className={styles.todo} {...props}>
          <span className={styles.dot} aria-hidden="true" />
          {issues.length} to finish
          <Icon name="chevronDown" size={14} />
        </button>
      )}
    >
      {(close) => (
        <div>
          <p className={styles.heading}>Before this can be submitted</p>
          <ul className={styles.list}>
            {issues.map((issue, i) => (
              <li key={i}>
                {issue.nodeId ? (
                  <Link
                    to={`/studio/courses/${courseId}/curriculum/${issue.nodeId}`}
                    onClick={close}
                    className={styles.link}
                  >
                    {issue.message}
                    <Icon name="arrowRight" size={14} />
                  </Link>
                ) : (
                  <Link
                    to={`/studio/courses/${courseId}/curriculum`}
                    onClick={close}
                    className={styles.link}
                  >
                    {issue.message}
                    <Icon name="arrowRight" size={14} />
                  </Link>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Popover>
  )
}
