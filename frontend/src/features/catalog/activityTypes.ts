import type { IconName } from '../../components/Icon'
import type { ActivitySummary } from '../../lib/api'
import { lessonActivities, type Lesson } from './treeUtils'

export const ACTIVITY_LABELS: Record<string, string> = {
  reading: 'Reading',
  video: 'Video',
  pdf: 'PDF',
  mcq: 'Quiz',
  workshop: 'Workshop',
  external_course: 'External course',
  manual_sim: 'Simulation',
  bot_sim: 'Chat simulation',
}

const ICONS: Record<string, IconName> = {
  reading: 'book',
  pdf: 'file',
  video: 'play',
  mcq: 'quiz',
  workshop: 'tool',
  external_course: 'external',
  manual_sim: 'chat',
  bot_sim: 'chat',
}

export function activityIcon(type: string): IconName {
  return ICONS[type] ?? 'book'
}

/** The lesson's primary activity (its first), used for the muted type icon. */
export function primaryActivity(lesson: Lesson): ActivitySummary | null {
  return lessonActivities(lesson)[0] ?? null
}

// What a learner will *do*, grouped for the "Includes" fact.
const MIX_ORDER: { label: string; types: string[] }[] = [
  { label: 'readings', types: ['reading', 'pdf'] },
  { label: 'videos', types: ['video'] },
  { label: 'quizzes', types: ['mcq'] },
  { label: 'workshops', types: ['workshop'] },
  { label: 'simulations', types: ['manual_sim', 'bot_sim'] },
  { label: 'external courses', types: ['external_course'] },
]

/** e.g. ["readings", "videos", "quizzes", "simulations"] — only kinds present. */
export function activityMix(lessons: Lesson[]): string[] {
  const present = new Set(
    lessons.flatMap((l) => lessonActivities(l).map((a) => a.activity_type)),
  )
  return MIX_ORDER.filter((g) => g.types.some((t) => present.has(t))).map((g) => g.label)
}
