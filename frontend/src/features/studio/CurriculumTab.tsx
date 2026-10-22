import { useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'

import { useMediaQuery } from '../../lib/useMediaQuery'
import { useBuilder } from './builderContext'
import styles from './CurriculumTab.module.css'
import { LessonEditor } from './LessonEditor'
import { ModuleEditor } from './ModuleEditor'
import { OutlineTree } from './OutlineTree'
import { studioApi } from './studioApi'
import { findLessonOf, findNode } from './treeHelpers'
import type { AuthCourse, AuthNode } from './types'

/** Return `course` with `parentId`'s children re-ordered to `ids`. */
function reorderLocal(course: AuthCourse, parentId: number, ids: number[]): AuthCourse {
  if (!course.tree?.root) return course
  const visit = (node: AuthNode): AuthNode => {
    if (node.id === parentId) {
      const byId = new Map(node.children.map((c) => [c.id, c]))
      return { ...node, children: ids.map((id) => byId.get(id)!).filter(Boolean) }
    }
    return { ...node, children: node.children.map(visit) }
  }
  return { ...course, tree: { ...course.tree, root: visit(course.tree.root) } }
}

export function CurriculumTab() {
  const { course, refresh, mutate } = useBuilder()
  const { nodeId } = useParams()
  const navigate = useNavigate()
  const narrow = useMediaQuery('(max-width: 899px)')
  const [error, setError] = useState<string | null>(null)
  const root = course.tree?.root
  if (!root) return null

  const base = `/studio/courses/${course.id}/curriculum`
  // Opening the curriculum lands you in the first lesson, not on an empty page.
  const firstLesson = root.children.flatMap((m) => m.children)[0]
  if (!nodeId && firstLesson) return <Navigate to={`${base}/${firstLesson.id}`} replace />
  const picked = nodeId ? findNode(root, Number(nodeId)) : null
  // A section lives inside its lesson's editor, so select that lesson.
  const selected = picked?.kind === 'subtopic' ? findLessonOf(root, picked.id) : picked
  const module =
    selected?.kind === 'topic'
      ? root.children.find((m) => m.children.some((l) => l.id === selected.id))
      : null
  const moduleNumber = module ? root.children.indexOf(module) + 1 : 0

  async function add(parentId: number, title: string) {
    const node = await studioApi.addNode(course.id, parentId, title)
    await refresh()
    navigate(`${base}/${node.id}`)
  }

  async function reorder(parentId: number, ids: number[]) {
    setError(null)
    mutate((c) => reorderLocal(c, parentId, ids)) // optimistic
    try {
      await studioApi.reorderChildren(parentId, ids)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Couldn’t reorder.')
      await refresh() // roll back to the server's order
    }
  }

  const outline = (
    <OutlineTree
      root={root}
      selectedId={selected?.id ?? null}
      editable={course.editable}
      onSelect={(id) => navigate(`${base}/${id}`)}
      onAddModule={(title) => add(root.id, title)}
      onAddLesson={(moduleId, title) => add(moduleId, title)}
      onReorder={(parentId, ids) => void reorder(parentId, ids)}
    />
  )

  return (
    <div className={styles.layout}>
      <aside className={styles.outline}>
        {narrow ? (
          <details open={!selected}>
            <summary className={styles.summary}>Outline</summary>
            {outline}
          </details>
        ) : (
          <>
            <div className={styles.outlineHead}>
              <h2>Outline</h2>
              <span>
                {root.children.length} module{root.children.length === 1 ? '' : 's'}
              </span>
            </div>
            {outline}
          </>
        )}
      </aside>

      <section className={styles.canvas}>
        <div className={styles.inner}>
        {!course.editable && (
          <p className={styles.locked} role="status">
            {course.status.key === 'in_review'
              ? 'This course is waiting to be published, so it’s locked for editing.'
              : 'You’re looking at the published course. Use “Edit course” to make changes.'}
          </p>
        )}
        {error && (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        )}

        {selected?.kind === 'topic' && module ? (
          <LessonEditor
            key={selected.id}
            lesson={selected}
            moduleTitle={module.title}
            moduleNumber={moduleNumber}
            onDeleted={() => navigate(base)}
          />
        ) : selected?.kind === 'segment' ? (
          <ModuleEditor
            key={selected.id}
            module={selected}
            number={root.children.indexOf(selected) + 1}
            onDeleted={() => navigate(base)}
          />
        ) : (
          <div className={styles.empty}>
            <h2>{root.children.length === 0 ? 'Build your curriculum' : 'Pick something to edit'}</h2>
            <p>
              {root.children.length === 0
                ? 'Add a module from the outline, then lessons inside it. Or bring in an existing plan from a spreadsheet.'
                : 'Select a lesson in the outline, or add a new one where you want it.'}
            </p>
            {course.editable && root.children.length === 0 && (
              <Link to={`/studio/courses/${course.id}/import`} className="btn">
                Import from a spreadsheet
              </Link>
            )}
          </div>
        )}
        </div>
      </section>
    </div>
  )
}
