import { useState } from 'react'

import { Icon } from '../../components/Icon'
import { ModuleMarker } from '../catalog/ModuleMarker'
import { InlineAdd } from './InlineAdd'
import styles from './OutlineTree.module.css'
import { SortableList } from './SortableList'
import { lessonIssues } from './readiness'
import type { AuthNode } from './types'

interface Props {
  root: AuthNode
  selectedId: number | null
  editable: boolean
  onSelect: (id: number) => void
  onAddModule: (title: string) => Promise<void>
  onAddLesson: (moduleId: number, title: string) => Promise<void>
  onReorder: (parentId: number, ids: number[]) => void
}

/** A lesson's state at a glance: a quiet tick when it's ready, an amber ring
 * when something's left. Text for screen readers, never colour alone. */
function LessonMark({ issues }: { issues: number }) {
  return issues === 0 ? (
    <span className={`${styles.mark} ${styles.ready}`} title="Ready">
      <Icon name="check" size={10} strokeWidth={2.4} />
      <span className="sr-only">Ready</span>
    </span>
  ) : (
    <span className={`${styles.mark} ${styles.todo}`} title={`${issues} to finish`}>
      <span className="sr-only">{issues} to finish</span>
    </span>
  )
}

/** The course as a quiet outline: modules and lessons, with drag handles
 * for sibling order and "+ Add" where the new thing will appear. */
export function OutlineTree({
  root,
  selectedId,
  editable,
  onSelect,
  onAddModule,
  onAddLesson,
  onReorder,
}: Props) {
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())
  const toggle = (id: number) =>
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <nav className={styles.tree} aria-label="Course outline">
      {root.children.length === 0 && (
        <p className={styles.empty}>
          Start with your first module — a big topic like “Product fundamentals”.
        </p>
      )}

      <SortableList
        items={root.children}
        disabled={!editable}
        handleLabel={(m) => `module ${m.title}`}
        onReorder={(ids) => onReorder(root.id, ids)}
      >
        {(module, index) => {
          const open = !collapsed.has(module.id)
          return (
            <div className={styles.module}>
              <div className={`${styles.row} ${selectedId === module.id ? styles.selected : ''}`}>
                <button
                  type="button"
                  className={styles.chevron}
                  aria-expanded={open}
                  aria-label={`${open ? 'Collapse' : 'Expand'} ${module.title}`}
                  onClick={() => toggle(module.id)}
                >
                  <Icon name={open ? 'chevronDown' : 'chevronRight'} size={14} />
                </button>
                <ModuleMarker number={index + 1} size="sm" />
                <button
                  type="button"
                  className={styles.name}
                  aria-current={selectedId === module.id ? 'page' : undefined}
                  onClick={() => onSelect(module.id)}
                >
                  {module.title}
                </button>
                {module.children.length === 0 && (
                  <span className={styles.hint}>empty</span>
                )}
              </div>

              {open && (
                <div className={styles.lessons}>
                  <SortableList
                    items={module.children}
                    disabled={!editable}
                    handleLabel={(l) => `lesson ${l.title}`}
                    onReorder={(ids) => onReorder(module.id, ids)}
                  >
                    {(lesson) => (
                      <div
                        className={`${styles.row} ${styles.lessonRow} ${
                          selectedId === lesson.id ? styles.selected : ''
                        }`}
                      >
                        <LessonMark issues={lessonIssues(lesson).length} />
                        <button
                          type="button"
                          className={styles.name}
                          aria-current={selectedId === lesson.id ? 'page' : undefined}
                          onClick={() => onSelect(lesson.id)}
                        >
                          {lesson.title}
                        </button>
                      </div>
                    )}
                  </SortableList>
                  <div className={styles.add}>
                    <InlineAdd
                      label="Add lesson"
                      placeholder="Lesson title"
                      disabled={!editable}
                      onAdd={(title) => onAddLesson(module.id, title)}
                    />
                  </div>
                </div>
              )}
            </div>
          )
        }}
      </SortableList>

      <div className={styles.addModule}>
        <InlineAdd
          label="Add module"
          placeholder="Module title"
          disabled={!editable}
          onAdd={onAddModule}
        />
      </div>
    </nav>
  )
}
