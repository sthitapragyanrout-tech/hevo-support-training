import styles from './ProgressBar.module.css'

interface Props {
  value: number
  max: number
  /** Accessible name, e.g. "Course progress". */
  label: string
}

/** Rendered only once real progress exists (see useProgress). */
export function ProgressBar({ value, max, label }: Props) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div
      className={styles.track}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      aria-valuetext={`${value} of ${max} lessons completed`}
    >
      <div className={styles.fill} style={{ width: `${pct}%` }} />
    </div>
  )
}
