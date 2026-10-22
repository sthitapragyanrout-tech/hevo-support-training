import { useState } from 'react'

import { Icon } from '../../components/Icon'
import { AutosaveField } from './AutosaveField'
import { useBuilder } from './builderContext'
import { ConfirmDialog } from './ConfirmDialog'
import styles from './LessonEditor.module.css'
import { studioApi } from './studioApi'
import type { AuthNode } from './types'

export function ModuleEditor({
  module,
  number,
  onDeleted,
}: {
  module: AuthNode
  number: number
  onDeleted: () => void
}) {
  const { course, refresh } = useBuilder()
  const editable = course.editable
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save(changes: Parameters<typeof studioApi.updateNode>[1]) {
    await studioApi.updateNode(module.id, changes)
    await refresh()
  }

  async function remove() {
    setBusy(true)
    try {
      await studioApi.deleteNode(module.id)
      setConfirm(false)
      await refresh()
      onDeleted()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Couldn’t delete that.')
      setConfirm(false)
    } finally {
      setBusy(false)
    }
  }

  const lessons = module.children.length
  const sections = module.children.reduce((n, l) => n + l.children.length, 0)

  return (
    <article className={styles.editor}>
      <header className={styles.header}>
        <p className={styles.crumb}>Module {String(number).padStart(2, '0')}</p>
        <AutosaveField
          label="Module title"
          hideLabel
          compact
          value={module.title}
          required
          ghost
          size="title"
          disabled={!editable}
          onSave={(title) => save({ title })}
        />
      </header>
      <AutosaveField
        label="What is this module about?"
        hint="One or two sentences shown under the module’s name on the course page."
        value={module.description}
        multiline
        rows={3}
        disabled={!editable}
        onSave={(description) => save({ description })}
      />
      <p className={styles.empty}>
        {lessons === 0
          ? 'This module has no lessons yet. Add one from the outline.'
          : `${lessons} lesson${lessons === 1 ? '' : 's'}, ${sections} section${sections === 1 ? '' : 's'}. Select a lesson in the outline to edit it.`}
      </p>
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
      {editable && (
        <div className={styles.danger}>
          <button type="button" className={styles.delete} onClick={() => setConfirm(true)}>
            <Icon name="trash" size={14} /> Delete module
          </button>
        </div>
      )}
      {confirm && (
        <ConfirmDialog
          title={`Delete module “${module.title}”?`}
          confirmLabel="Delete module"
          busy={busy}
          onCancel={() => setConfirm(false)}
          onConfirm={() => void remove()}
        >
          <p>
            {lessons > 0
              ? `This also removes its ${lessons} lesson${lessons === 1 ? '' : 's'} and everything inside them.`
              : 'This module is empty.'}
          </p>
        </ConfirmDialog>
      )}
    </article>
  )
}
