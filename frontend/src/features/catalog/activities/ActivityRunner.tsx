import type { ComponentType } from 'react'

import { activityIcon, ACTIVITY_LABELS } from '../activityTypes'
import { ActivityShell } from './ActivityShell'
import styles from './ActivityRunner.module.css'
import { ManualSimActivity } from './ManualSimActivity'
import { QuizActivity } from './QuizActivity'
import { ReadingActivity } from './ReadingActivity'
import { SimActivity } from './SimActivity'
import { VideoActivity } from './VideoActivity'
import type { RendererProps } from './types'

/** The learner-side half of the activity registry: which component runs
 * which type. A new activity type ships by adding one line here. */
const RENDERERS: Record<string, ComponentType<RendererProps>> = {
  reading: ReadingActivity,
  mcq: QuizActivity,
  video: VideoActivity,
  bot_sim: SimActivity,
  manual_sim: ManualSimActivity,
}

/** Types without a renderer yet keep the same frame and say so plainly. */
function Upcoming({ activity }: RendererProps) {
  const label = ACTIVITY_LABELS[activity.activity_type] ?? activity.activity_type
  return (
    <ActivityShell
      icon={activityIcon(activity.activity_type)}
      title={activity.title}
      meta={`${label} · ${activity.is_required ? 'Required' : 'Optional'}`}
    >
      <span className={styles.soon}>Available soon</span>
    </ActivityShell>
  )
}

export function ActivityRunner({ activity }: RendererProps) {
  const Renderer = RENDERERS[activity.activity_type] ?? Upcoming
  return <Renderer activity={activity} />
}
