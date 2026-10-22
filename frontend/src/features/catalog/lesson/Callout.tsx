import type { ReactNode } from 'react'

import { Icon, type IconName } from '../../../components/Icon'
import styles from './Callout.module.css'
import type { CalloutKind } from './remarkCallouts'

const META: Record<CalloutKind, { label: string; icon: IconName }> = {
  idea: { label: 'Key idea', icon: 'bulb' },
  why: { label: 'Why this matters', icon: 'target' },
  support: { label: 'Support lens', icon: 'search' },
  scenario: { label: 'Customer scenario', icon: 'chat' },
  pitfall: { label: 'Common pitfall', icon: 'alert' },
  takeaway: { label: 'Takeaway', icon: 'bookmark' },
}

interface Props {
  kind: CalloutKind
  title?: string
  children: ReactNode
}

/** A lightweight learning marker. Meaning is carried by the visible label
 * and icon, not by color. Each kind has its own treatment (see the css). */
export function Callout({ kind, title, children }: Props) {
  const { label, icon } = META[kind]
  return (
    <div className={`${styles.callout} ${styles[kind]}`} role="note" aria-label={label}>
      <p className={styles.label}>
        <Icon name={icon} size={14} />
        {label}
      </p>
      {title && <p className={styles.title}>{title}</p>}
      <div className={styles.body}>{children}</div>
    </div>
  )
}
