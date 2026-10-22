import { composeCourseIntro, parseCourseIntro } from '../catalog/courseIntro'
import {
  flattenLessons,
  formatMinutes,
  getModules,
  pluralize,
  totalMinutes,
} from '../catalog/treeUtils'
import { AutosaveField } from './AutosaveField'
import { useBuilder } from './builderContext'
import styles from './OverviewTab.module.css'
import { studioApi } from './studioApi'

export function OverviewTab() {
  const { course, refresh } = useBuilder()
  const root = course.tree?.root
  const editable = course.editable
  if (!root) return null

  const { lead, outcomes } = parseCourseIntro(root.description)
  const modules = getModules(root)
  const lessons = flattenLessons(modules)
  const minutes = totalMinutes(lessons)

  async function save(changes: { title?: string; description?: string }) {
    await studioApi.updateOverview(course.id, changes)
    await refresh()
  }

  return (
    <div className={styles.page}>
      <p className={styles.summary}>
        {pluralize(modules.length, 'module')} · {pluralize(lessons.length, 'lesson')}
        {minutes != null && ` · about ${formatMinutes(minutes)}`}
      </p>

      <AutosaveField
        label="Course title"
        hideLabel
        compact
        value={root.title}
        required
        ghost
        disabled={!editable}
        size="title"
        onSave={(title) => save({ title })}
      />

      <AutosaveField
        label="What is this course for?"
        hint="Shown at the top of the course page. Say why it matters, in a sentence or two."
        value={lead.join('\n\n')}
        multiline
        rows={5}
        disabled={!editable}
        onSave={(text) =>
          save({ description: composeCourseIntro(text.split(/\n\s*\n/), outcomes) })
        }
      />

      <AutosaveField
        label="What will learners be able to do afterwards?"
        hint="One per line, starting with a verb: “Diagnose common ingestion failures”."
        value={outcomes.join('\n')}
        multiline
        rows={5}
        disabled={!editable}
        onSave={(text) => save({ description: composeCourseIntro(lead, text.split('\n')) })}
      />
    </div>
  )
}
