import { Icon } from '../../components/Icon'
import styles from './ModuleMarker.module.css'

interface Props {
  number: number
  /** `current` = the module holding the lesson being read / next to start.
   * `complete` only ever appears once real progress exists. */
  state?: 'default' | 'current' | 'complete' | 'locked'
  size?: 'sm' | 'md'
}

/** The numbered module dot used on the landing journey, the sidebar rail and
 * the lesson eyebrow — one visual language for "where am I". */
export function ModuleMarker({ number, state = 'default', size = 'md' }: Props) {
  return (
    <span className={`${styles.marker} ${styles[size]} ${styles[state]}`} aria-hidden="true">
      {state === 'complete' ? (
        <Icon name="check" size={size === 'sm' ? 11 : 14} strokeWidth={2} />
      ) : state === 'locked' ? (
        <Icon name="lock" size={size === 'sm' ? 11 : 14} strokeWidth={1.75} />
      ) : (
        String(number).padStart(2, '0')
      )}
    </span>
  )
}
