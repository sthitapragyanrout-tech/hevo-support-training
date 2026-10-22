import type { ActivitySummary, TreeNode } from '../../lib/api'

/* Learner vocabulary is Course → Module → Lesson, and a lesson is made of
 * Sections. In the data these are root → `segment` → `topic` → `subtopic`.
 * Sections are content grouping *inside* a lesson page, never a level of
 * navigation. (Authoring uses the same words — see features/studio.) */

export interface Lesson {
  /** The `topic` node. Its own description is the lesson intro. */
  node: TreeNode
  /** The lesson's `subtopic` children, in order (possibly none). */
  sections: TreeNode[]
  moduleId: number
  moduleNumber: number
  /** 1-based position across the whole course (prev/next order). */
  position: number
}

export interface Module {
  node: TreeNode
  number: number
  lessons: Lesson[]
}

/** Root-to-node chain for `nodeId`, or null if it isn't in the tree. */
export function findPath(root: TreeNode, nodeId: number): TreeNode[] | null {
  if (root.id === nodeId) return [root]
  for (const child of root.children) {
    const sub = findPath(child, nodeId)
    if (sub) return [root, ...sub]
  }
  return null
}

/** Modules (the course's children) with their numbered lessons. */
export function getModules(root: TreeNode): Module[] {
  let position = 0
  return root.children.map((moduleNode, i) => ({
    node: moduleNode,
    number: i + 1,
    lessons: moduleNode.children.map((lessonNode) => ({
      node: lessonNode,
      sections: lessonNode.children,
      moduleId: moduleNode.id,
      moduleNumber: i + 1,
      position: ++position,
    })),
  }))
}

export function flattenLessons(modules: Module[]): Lesson[] {
  return modules.flatMap((m) => m.lessons)
}

export function moduleComplete(module: Module, completed: Set<number>): boolean {
  return module.lessons.length > 0 && module.lessons.every((l) => completed.has(l.node.id))
}

export function lessonNeighbors(
  lessons: Lesson[],
  nodeId: number,
): { previous: Lesson | null; next: Lesson | null } {
  const i = lessons.findIndex((l) => l.node.id === nodeId)
  if (i === -1) return { previous: null, next: null }
  return { previous: lessons[i - 1] ?? null, next: lessons[i + 1] ?? null }
}

/** Where a node id that isn't a lesson should land: a section → its lesson
 * (scrolled to the section); a module → its first lesson. */
export function resolveLessonTarget(
  modules: Module[],
  nodeId: number,
): { lessonId: number; sectionId: number | null } | null {
  for (const module of modules) {
    if (module.node.id === nodeId) {
      const first = module.lessons[0]
      return first ? { lessonId: first.node.id, sectionId: null } : null
    }
    for (const lesson of module.lessons) {
      if (lesson.sections.some((s) => s.id === nodeId)) {
        return { lessonId: lesson.node.id, sectionId: nodeId }
      }
    }
  }
  return null
}

export function firstIncompleteLesson(lessons: Lesson[], completed: Set<number>): Lesson | null {
  return lessons.find((l) => !completed.has(l.node.id)) ?? null
}

/** Every activity in a lesson: its own, then each section's, in order. */
export function lessonActivities(lesson: Lesson): ActivitySummary[] {
  return [...lesson.node.activities, ...lesson.sections.flatMap((s) => s.activities)]
}

/** A lesson's duration: its own estimate, else the sum of its sections'. */
export function lessonMinutes(lesson: Lesson): number | null {
  if (lesson.node.estimated_minutes != null) return lesson.node.estimated_minutes
  const known = lesson.sections
    .map((s) => s.estimated_minutes)
    .filter((m): m is number => m != null)
  return known.length === 0 ? null : known.reduce((a, b) => a + b, 0)
}

/** Sum of lesson minutes; null when no lesson has an estimate. */
export function totalMinutes(lessons: Lesson[]): number | null {
  const known = lessons.map(lessonMinutes).filter((m): m is number => m != null)
  return known.length === 0 ? null : known.reduce((a, b) => a + b, 0)
}

/** Required activities in the lesson that a learner can finish today and
 * hasn't yet — what stands between them and "Mark complete". */
export function pendingRequired(
  lesson: Lesson,
  activities: Record<number, string | undefined>,
): ActivitySummary[] {
  return lessonActivities(lesson).filter(
    (a) =>
      a.is_required &&
      a.completable &&
      activities[a.id] !== 'completed' &&
      activities[a.id] !== 'exhausted', // out of attempts: scored, not passed, free to move on
  )
}

export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m === 0 ? `${h}h` : `${h}h ${String(m).padStart(2, '0')}m`
}

export function pluralize(n: number, singular: string): string {
  return `${n} ${singular}${n === 1 ? '' : 's'}`
}

/** Case-insensitive match on a lesson's title, intro, sections and module title. */
export function searchLessons(modules: Module[], query: string): Lesson[] {
  const q = query.trim().toLowerCase()
  if (!q) return flattenLessons(modules)
  return flattenLessons(modules).filter((l) => {
    const moduleTitle = modules.find((m) => m.node.id === l.moduleId)?.node.title ?? ''
    const texts = [
      l.node.title,
      l.node.description,
      moduleTitle,
      ...l.sections.flatMap((s) => [s.title, s.description]),
    ]
    return texts.some((s) => s.toLowerCase().includes(q))
  })
}

/** First prose paragraph of a Markdown description as plain text, for list
 * rows. Skips headings, callouts, code, lists and "lead-in:" lines, and cuts
 * at a sentence (or word) boundary rather than mid-word. */
export function summarize(markdown: string, maxLength = 140): string {
  const firstBlock = markdown
    .split(/\n\s*\n/)
    .map((b) => b.trim())
    .find((b) => b && !/^(#|```|>|[-*] |\d+\. )/.test(b) && !b.endsWith(':'))
  if (!firstBlock) return ''
  const plain = firstBlock
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[*_`]/g, '')
    .replace(/\s+/g, ' ')
  if (plain.length <= maxLength) return plain
  const cut = plain.slice(0, maxLength)
  const sentenceEnd = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('? '), cut.lastIndexOf('! '))
  if (sentenceEnd > maxLength * 0.4) return cut.slice(0, sentenceEnd + 1)
  return `${cut.slice(0, cut.lastIndexOf(' ')).trimEnd()}…`
}
