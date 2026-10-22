import type { AuthNode } from './types'

export interface ReadinessIssue {
  message: string
  /** The module or lesson to open to fix it (null = course level). */
  nodeId: number | null
}

/** What stands between this draft and "Submit": the same rules the server's
 * publish checklist enforces, computed locally so the author sees progress
 * as they type. (The server stays the authority when you submit.) */
export function readiness(root: AuthNode | null | undefined): ReadinessIssue[] {
  if (!root) return []
  const issues: ReadinessIssue[] = []
  if (root.children.length === 0) {
    return [{ message: 'Add your first module.', nodeId: null }]
  }
  for (const module of root.children) {
    if (module.children.length === 0) {
      issues.push({ message: `Module “${module.title}” has no lessons yet.`, nodeId: module.id })
    }
    for (const lesson of module.children) issues.push(...lessonIssues(lesson))
  }
  return issues
}

/** Problems inside one lesson (empty, or activities still needing setup). */
export function lessonIssues(lesson: AuthNode): ReadinessIssue[] {
  const issues: ReadinessIssue[] = []
  const hasContent =
    lesson.description.trim() !== '' || lesson.children.length > 0 || lesson.activities.length > 0
  if (!hasContent) {
    issues.push({ message: `Lesson “${lesson.title}” is empty.`, nodeId: lesson.id })
  }
  for (const holder of [lesson, ...lesson.children]) {
    for (const activity of holder.activities) {
      if (activity.needs_setup) {
        issues.push({
          message: `“${activity.title}” in “${holder.title}” needs setup.`,
          nodeId: lesson.id,
        })
      }
    }
  }
  return issues
}
