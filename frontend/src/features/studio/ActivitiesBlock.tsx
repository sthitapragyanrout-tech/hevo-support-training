import { useState, type ComponentType } from 'react'

import { Icon, type IconName } from '../../components/Icon'
import { Popover } from '../../components/Popover'
import { useBuilder } from './builderContext'
import { AutosaveField } from './AutosaveField'
import { QuizEditor, type EditorProps } from './QuizEditor'
import { BotSimEditor } from './BotSimEditor'
import { ManualSimEditor } from './ManualSimEditor'
import { SchemaForm } from './SchemaForm'
import { VideoEditor } from './VideoEditor'
import styles from './ActivitiesBlock.module.css'
import { studioApi } from './studioApi'
import type { ActivityType, AuthActivity, AuthNode } from './types'
import { moveItem } from './treeHelpers'

/** Types with their own authoring screen; everything else gets the generic
 * form generated from the type's schema. */
const EDITORS: Record<string, ComponentType<EditorProps>> = {
  mcq: QuizEditor,
  video: VideoEditor,
  bot_sim: BotSimEditor,
  manual_sim: ManualSimEditor,
}

interface Props {
  node: AuthNode
  title: string
  emptyHint: string
}

/** The activities hanging off one lesson or section: reorder, configure
 * (form generated from the type's schema), delete, add. */
export function ActivitiesBlock({ node, title, emptyHint }: Props) {
  const { course, refresh, activityTypes } = useBuilder()
  const editable = course.editable
  const [error, setError] = useState<string | null>(null)
  const types = new Map(activityTypes.map((t) => [t.key, t]))

  async function run(task: () => Promise<unknown>) {
    setError(null)
    try {
      await task()
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    }
  }

  function move(index: number, by: -1 | 1) {
    const ids = moveItem(node.activities, index, index + by).map((a) => a.id)
    void run(() => studioApi.reorderActivities(node.id, ids))
  }

  // A locked course with nothing here has nothing to show (no editing prompts).
  if (!editable && node.activities.length === 0) return null

  return (
    <section className={styles.block} aria-label={title}>
      <header className={styles.head}>
        <h4 className={styles.title}>{title}</h4>
        {node.activities.length > 0 && <span className={styles.count}>{node.activities.length}</span>}
      </header>

      {node.activities.length === 0 && <p className={styles.empty}>{emptyHint}</p>}

      {node.activities.length > 0 && (
        <ol className={styles.list}>
          {node.activities.map((activity, i) => (
            <ActivityRow
              key={activity.id}
              activity={activity}
              type={types.get(activity.activity_type)}
              editable={editable}
              canMoveUp={i > 0}
              canMoveDown={i < node.activities.length - 1}
              onMove={(by) => move(i, by)}
              onSaved={() => refresh()}
              onDelete={() => run(() => studioApi.deleteActivity(activity.id))}
            />
          ))}
        </ol>
      )}

      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}

      {editable && (
        <Popover
          label="Choose an activity type"
          width={320}
          trigger={(props) => (
            <button type="button" className={`btn btn-ghost btn-sm ${styles.add}`} {...props}>
              <Icon name="plus" size={14} /> Add activity
            </button>
          )}
        >
          {(close) => (
            <ul className={styles.menu} role="menu" aria-label="Activity types">
              {activityTypes.map((type) => (
                <li key={type.key} role="none">
                  <button
                    type="button"
                    role="menuitem"
                    className={styles.option}
                    onClick={() => {
                      close()
                      void run(() => studioApi.addActivity(node.id, type.key))
                    }}
                  >
                    <span className={styles.tile}>
                      <Icon name={(type.icon as IconName) ?? 'book'} size={16} />
                    </span>
                    <span>
                      <strong>{type.label}</strong>
                      <span className={styles.desc}>{type.description}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Popover>
      )}
    </section>
  )
}

interface RowProps {
  activity: AuthActivity
  type: ActivityType | undefined
  editable: boolean
  canMoveUp: boolean
  canMoveDown: boolean
  onMove: (by: -1 | 1) => void
  onSaved: () => Promise<void>
  onDelete: () => void
}

function ActivityRow({
  activity,
  type,
  editable,
  canMoveUp,
  canMoveDown,
  onMove,
  onSaved,
  onDelete,
}: RowProps) {
  const [open, setOpen] = useState(activity.needs_setup)
  const Editor = EDITORS[activity.activity_type]

  async function save(changes: Parameters<typeof studioApi.updateActivity>[1]) {
    await studioApi.updateActivity(activity.id, changes)
    await onSaved()
  }

  return (
    <li className={styles.row}>
      <div className={styles.line}>
        <span className={styles.tile} title={type?.label}>
          <Icon name={(type?.icon as IconName) ?? 'book'} size={16} />
        </span>
        <div className={styles.name}>
          <AutosaveField
            label="Activity title"
            hideLabel
            compact
            ghost
            required
            value={activity.title}
            disabled={!editable}
            onSave={(title) => save({ title })}
          />
        </div>
        <span className={styles.typeLabel}>{type?.label ?? activity.activity_type}</span>
        {activity.needs_setup && (
          <span className={styles.setup}>
            <span className={styles.setupDot} aria-hidden="true" />
            Needs setup
          </span>
        )}
        <div className={styles.tools}>
          {editable && (
            <>
              <button
                type="button"
                className="icon-btn"
                aria-label={`Move “${activity.title}” up`}
                disabled={!canMoveUp}
                onClick={() => onMove(-1)}
              >
                <Icon name="arrowUp" size={14} />
              </button>
              <button
                type="button"
                className="icon-btn"
                aria-label={`Move “${activity.title}” down`}
                disabled={!canMoveDown}
                onClick={() => onMove(1)}
              >
                <Icon name="arrowDown" size={14} />
              </button>
              <button
                type="button"
                className="icon-btn"
                aria-label={`Delete “${activity.title}”`}
                onClick={onDelete}
              >
                <Icon name="trash" size={14} />
              </button>
            </>
          )}
          <button
            type="button"
            className="icon-btn"
            aria-expanded={open}
            aria-label={`${open ? 'Hide' : 'Show'} settings for “${activity.title}”`}
            onClick={() => setOpen((o) => !o)}
          >
            <Icon name={open ? 'chevronDown' : 'chevronRight'} size={14} />
          </button>
        </div>
      </div>

      {open && (
        <div className={styles.settings}>
          {type && Editor ? (
            <Editor activity={activity} disabled={!editable} save={save} refresh={onSaved} />
          ) : type ? (
            <SchemaForm
              schema={type.config_schema}
              value={activity.config}
              disabled={!editable}
              onChange={(config) => save({ config })}
            />
          ) : (
            <p className={styles.empty}>This activity type isn’t available any more.</p>
          )}
          <div className={styles.meta}>
            <label className={styles.check}>
              <input
                type="checkbox"
                checked={activity.is_required}
                disabled={!editable}
                onChange={(e) => void save({ is_required: e.target.checked })}
              />
              Required
            </label>
            <label className={styles.points}>
              Points
              <input
                type="number"
                min={0}
                className="input"
                defaultValue={activity.points}
                disabled={!editable}
                onBlur={(e) => {
                  const points = Number(e.target.value)
                  if (points !== activity.points && points >= 0) void save({ points })
                }}
              />
            </label>
          </div>
        </div>
      )}
    </li>
  )
}
