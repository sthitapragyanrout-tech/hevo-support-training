import type { LessonStatus } from '../../components/StatusIcon'
import { moduleComplete, type Lesson, type Module } from './treeUtils'
import { hasStarted, type Progress } from './useProgress'

/** How one lesson reads for this learner. Finished wins over everything (a
 * lesson you've done is never locked and keeps its tick); then where you are;
 * then locked; then the one the server says is next. */
export function lessonStatus(
  lesson: Lesson,
  progress: Progress,
  currentId: number | null = null,
): LessonStatus {
  const id = lesson.node.id
  if (progress.completed.has(id)) return 'completed'
  if (progress.lockOf(id)) return 'locked'
  if (id === currentId) return 'current'
  if (progress.nextLessonId === id) return 'next'
  return 'not_started'
}

/** A module is locked when its first lesson is and nothing in it is finished. */
export function moduleMarker(
  module: Module,
  progress: Progress,
  activeModuleId: number | null,
): 'default' | 'current' | 'complete' | 'locked' {
  if (hasStarted(progress) && moduleComplete(module, progress.completed)) return 'complete'
  const first = module.lessons[0]
  const anyDone = module.lessons.some((l) => progress.completed.has(l.node.id))
  if (first && !anyDone && progress.lockOf(first.node.id)) return 'locked'
  return module.node.id === activeModuleId ? 'current' : 'default'
}

/** "Unlocks when you complete X", for a locked lesson (else null). */
export function unlockHint(lesson: Lesson, progress: Progress): string | null {
  const lock = progress.lockOf(lesson.node.id)
  return lock && !progress.completed.has(lesson.node.id)
    ? `Unlocks when you complete “${lock.title}”`
    : null
}
