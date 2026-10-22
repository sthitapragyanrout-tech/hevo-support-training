import type { CourseStatus } from './types'
import styles from './StageStepper.module.css'

type Step = { key: string; label: string }
const STEPS: Step[] = [
  { key: 'build', label: 'Build' },
  { key: 'review', label: 'Review' },
  { key: 'live', label: 'Live' },
]

/** Where the course is on its way to learners. Which step is current comes
 * from the course status; it is a picture of the lifecycle, not a control. */
function position(status: CourseStatus['key']): { current: number; done: number } {
  switch (status) {
    case 'draft':
      return { current: 0, done: 0 }
    case 'in_review':
      return { current: 1, done: 1 }
    case 'published':
      return { current: 2, done: 3 }
    case 'published_with_draft':
      return { current: 0, done: 0 } // building the next version; the old one is still live
    default:
      return { current: -1, done: 0 }
  }
}

export function StageStepper({ status }: { status: CourseStatus }) {
  const { current, done } = position(status.key)
  const hasLive = status.key === 'published_with_draft'

  return (
    <ol className={styles.stepper} aria-label="Course progress to publishing">
      {STEPS.map((step, i) => {
        const state = i < done ? 'done' : i === current ? 'current' : 'todo'
        const live = hasLive && i === 2
        return (
          <li
            key={step.key}
            className={`${styles.step} ${styles[live ? 'done' : state]}`}
            aria-current={i === current ? 'step' : undefined}
          >
            <span className={styles.dot} aria-hidden="true">
              {(state === 'done' || live) && '✓'}
            </span>
            {step.label}
            <span className="sr-only">
              {live ? ' (the previous version is live)' : state === 'done' ? ' (done)' : ''}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
