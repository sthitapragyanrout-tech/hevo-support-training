import { useState } from 'react'

import { Icon } from '../../components/Icon'
import { ActivitiesBlock } from './ActivitiesBlock'
import { AutosaveField } from './AutosaveField'
import { useBuilder } from './builderContext'
import { ConfirmDialog } from './ConfirmDialog'
import { InlineAdd } from './InlineAdd'
import styles from './LessonEditor.module.css'
import { MarkdownEditor } from './MarkdownEditor'
import { SectionBlock } from './SectionBlock'
import { studioApi } from './studioApi'
import { moveItem } from './treeHelpers'
import type { AuthNode } from './types'

interface Props {
  lesson: AuthNode
  moduleTitle: string
  moduleNumber: number
  onDeleted: () => void
}

export function LessonEditor({ lesson, moduleTitle, moduleNumber, onDeleted }: Props) {
  const { course, refresh } = useBuilder()
  const editable = course.editable
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<{ kind: 'lesson' | 'section'; node: AuthNode } | null>(null)
  const [impact, setImpact] = useState<string>('')
  const [busy, setBusy] = useState(false)

  async function saveLesson(changes: Parameters<typeof studioApi.updateNode>[1]) {
    await studioApi.updateNode(lesson.id, changes)
    await refresh()
  }

  async function moveSection(index: number, by: -1 | 1) {
    setError(null)
    try {
      await studioApi.reorderChildren(
        lesson.id,
        moveItem(lesson.children, index, index + by).map((s) => s.id),
      )
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Couldn’t reorder.')
    }
  }

  async function ask(kind: 'lesson' | 'section', node: AuthNode) {
    const found = await studioApi.nodeImpact(node.id).catch(() => null)
    const parts: string[] = []
    if (found?.sections) parts.push(`${found.sections} section${found.sections === 1 ? '' : 's'}`)
    const own = node.activities.length + (found?.activities ?? 0)
    if (own) parts.push(`${own} activit${own === 1 ? 'y' : 'ies'}`)
    setImpact(parts.length ? `This also removes ${parts.join(' and ')}.` : '')
    setConfirm({ kind, node })
  }

  async function remove() {
    if (!confirm) return
    setBusy(true)
    try {
      await studioApi.deleteNode(confirm.node.id)
      const wasLesson = confirm.kind === 'lesson'
      setConfirm(null)
      await refresh()
      if (wasLesson) onDeleted()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Couldn’t delete that.')
      setConfirm(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className={styles.editor}>
      <header className={styles.header}>
        <p className={styles.crumb}>
          Module {String(moduleNumber).padStart(2, '0')} · {moduleTitle}
        </p>
        <AutosaveField
          label="Lesson title"
          hideLabel
          compact
          value={lesson.title}
          required
          ghost
          size="title"
          disabled={!editable}
          onSave={(title) => saveLesson({ title })}
        />
      </header>

      <MarkdownEditor
        label="Introduction"
        hint="The opening hook — what this lesson is and why it matters, in a couple of sentences."
        value={lesson.description}
        disabled={!editable}
        rows={6}
        onSave={(description) => saveLesson({ description })}
      />

      <div className={styles.sections}>
        <div className={styles.sectionsHead}>
          <h3 className={styles.heading}>Sections</h3>
          <span className={styles.count}>{lesson.children.length}</span>
        </div>
        {lesson.children.length === 0 && editable && (
          <p className={styles.empty}>
            A lesson can be just an introduction, or be broken into sections that each have their
            own content and activities.
          </p>
        )}
        {lesson.children.map((section, i) => (
          <SectionBlock
            key={section.id}
            section={section}
            number={i + 1}
            canMoveUp={i > 0}
            canMoveDown={i < lesson.children.length - 1}
            onMove={(by) => void moveSection(i, by)}
            onDelete={() => void ask('section', section)}
          />
        ))}
        <div className={styles.addSection}>
        <InlineAdd
          label="Add section"
          placeholder="Section title, e.g. Sources & Destinations"
          disabled={!editable}
          onAdd={async (title) => {
            await studioApi.addNode(course.id, lesson.id, title)
            await refresh()
          }}
        />
        </div>
      </div>

      <ActivitiesBlock
        node={lesson}
        title="At the end of the lesson"
        emptyHint="Optional: a quiz or exercise that covers the whole lesson."
      />

      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}

      {editable && (
        <div className={styles.danger}>
          <button type="button" className={styles.delete} onClick={() => void ask('lesson', lesson)}>
            <Icon name="trash" size={14} /> Delete lesson
          </button>
        </div>
      )}

      {confirm && (
        <ConfirmDialog
          title={`Delete ${confirm.kind} “${confirm.node.title}”?`}
          confirmLabel={`Delete ${confirm.kind}`}
          busy={busy}
          onCancel={() => setConfirm(null)}
          onConfirm={() => void remove()}
        >
          <p>{impact || 'This can’t be undone from here.'}</p>
        </ConfirmDialog>
      )}
    </article>
  )
}
