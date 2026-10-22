import { Icon } from '../../components/Icon'
import { ModuleMarker } from '../catalog/ModuleMarker'
import { ActivitiesBlock } from './ActivitiesBlock'
import { AutosaveField } from './AutosaveField'
import { useBuilder } from './builderContext'
import { MarkdownEditor } from './MarkdownEditor'
import styles from './SectionBlock.module.css'
import { studioApi } from './studioApi'
import type { AuthNode } from './types'

interface Props {
  section: AuthNode
  number: number
  canMoveUp: boolean
  canMoveDown: boolean
  onMove: (by: -1 | 1) => void
  onDelete: () => void
}

/** One section of a lesson, laid out like it will read: a numbered heading,
 * its content, then what the learner does with it. */
export function SectionBlock({ section, number, canMoveUp, canMoveDown, onMove, onDelete }: Props) {
  const { course, refresh } = useBuilder()
  const editable = course.editable

  async function save(changes: Parameters<typeof studioApi.updateNode>[1]) {
    await studioApi.updateNode(section.id, changes)
    await refresh()
  }

  return (
    <section className={styles.block} aria-label={`Section ${number}: ${section.title}`}>
      <div className={styles.rail}>
        <ModuleMarker number={number} size="sm" />
      </div>
      <div className={styles.body}>
        <header className={styles.head}>
          <div className={styles.title}>
            <AutosaveField
              label="Section title"
              hideLabel
              ghost
              size="section"
              required
              compact
              value={section.title}
              disabled={!editable}
              onSave={(title) => save({ title })}
            />
          </div>
          <label className={styles.minutes}>
            <span className="sr-only">Minutes</span>
            <input
              type="number"
              min={0}
              className="input"
              placeholder="min"
              aria-label="Minutes"
              defaultValue={section.estimated_minutes ?? ''}
              disabled={!editable}
              onBlur={(e) => {
                const next = e.target.value.trim() === '' ? null : Number(e.target.value)
                if (next !== section.estimated_minutes) void save({ estimated_minutes: next })
              }}
            />
            <span aria-hidden="true">min</span>
          </label>
          {editable && (
            <div className={styles.tools}>
              <button
                type="button"
                className="icon-btn"
                aria-label={`Move “${section.title}” up`}
                disabled={!canMoveUp}
                onClick={() => onMove(-1)}
              >
                <Icon name="arrowUp" size={14} />
              </button>
              <button
                type="button"
                className="icon-btn"
                aria-label={`Move “${section.title}” down`}
                disabled={!canMoveDown}
                onClick={() => onMove(1)}
              >
                <Icon name="arrowDown" size={14} />
              </button>
              <button
                type="button"
                className="icon-btn"
                aria-label={`Delete section “${section.title}”`}
                onClick={onDelete}
              >
                <Icon name="trash" size={14} />
              </button>
            </div>
          )}
        </header>

        <MarkdownEditor
          label="Content"
          value={section.description}
          disabled={!editable}
          rows={5}
          onSave={(description) => save({ description })}
        />

        <ActivitiesBlock
          node={section}
          title="Activities"
          emptyHint="No activities yet — add a reading, quiz or exercise to practise this section."
        />
      </div>
    </section>
  )
}
