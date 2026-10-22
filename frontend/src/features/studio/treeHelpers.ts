import type { AuthNode } from './types'

export function findNode(root: AuthNode | null | undefined, id: number): AuthNode | null {
  if (!root) return null
  if (root.id === id) return root
  for (const child of root.children) {
    const found = findNode(child, id)
    if (found) return found
  }
  return null
}

export function* walk(node: AuthNode): Generator<AuthNode> {
  yield node
  for (const child of node.children) yield* walk(child)
}

/** How many activities in this subtree still need configuring. */
export function needsSetupCount(node: AuthNode): number {
  let count = 0
  for (const n of walk(node)) count += n.activities.filter((a) => a.needs_setup).length
  return count
}

export function findLessonOf(root: AuthNode | null | undefined, id: number): AuthNode | null {
  if (!root) return null
  for (const module of root.children) {
    for (const lesson of module.children) {
      if (lesson.id === id || lesson.children.some((s) => s.id === id)) return lesson
    }
  }
  return null
}

export function moveItem<T>(items: T[], from: number, to: number): T[] {
  const next = items.slice()
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  return next
}
