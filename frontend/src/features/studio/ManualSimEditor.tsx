import { useState } from 'react'

import { AutosaveField } from './AutosaveField'
import type { EditorProps } from './QuizEditor'
import styles from './ManualSimEditor.module.css'
import { useConfigWriter } from './useConfigWriter'

interface Criterion {
  key: string
  label: string
  description: string
  guidance: string
}

const MAX_CRITERIA = 8

const text = (value: unknown) => (typeof value === 'string' ? value : '')
const whole = (value: unknown, fallback: number) =>
  typeof value === 'number' && Number.isInteger(value) ? value : fallback

function criteriaOf(config: Record<string, unknown>): Criterion[] {
  const raw = Array.isArray(config.criteria) ? (config.criteria as Record<string, unknown>[]) : []
  return raw.map((c) => ({
    key: text(c.key),
    label: text(c.label),
    description: text(c.description),
    guidance: text(c.guidance),
  }))
}

function nextKey(existing: Criterion[]): string {
  const used = new Set(existing.map((c) => c.key))
  let n = existing.length + 1
  while (used.has(`c${n}`)) n += 1
  return `c${n}`
}

/** Set up a mentor-rated simulation: the task, the rubric, what it takes to pass, and the
 * deadlines. Every edit goes through one writer, so typing in two fields quickly can't undo
 * either. The raters' guidance is kept apart from what learners see. */
export function ManualSimEditor({ activity, disabled, save }: EditorProps) {
  const config = activity.config
  const criteria = criteriaOf(config)
  const threshold = typeof config.pass_threshold === 'number' ? config.pass_threshold : 0.7
  const minEach = whole(config.min_each, 0)
  const write = useConfigWriter(config, (next) => save({ config: next }))
  const [problem, setProblem] = useState<string | null>(null)

  function run(task: Promise<void>) {
    setProblem(null)
    task.catch((err) => setProblem(err instanceof Error ? err.message : 'That didn’t save.'))
  }

  const setCriteria = (change: (list: Criterion[]) => Criterion[]) =>
    write((cfg) => ({ ...cfg, criteria: change(criteriaOf(cfg)) }))
  const patch = (key: string, field: keyof Criterion, value: string) =>
    setCriteria((list) => list.map((c) => (c.key === key ? { ...c, [field]: value } : c)))

  async function savePass(value: string) {
    const n = Number(value)
    if (value.trim() === '' || Number.isNaN(n) || n < 1 || n > 5) throw new Error('Enter a pass mark from 1 to 5 (out of 5).')
    await write((cfg) => ({ ...cfg, pass_threshold: Math.round((n / 5) * 1000) / 1000 }))
  }

  async function saveMin(value: string) {
    const n = Number(value)
    if (value.trim() === '' || !Number.isInteger(n) || n < 0 || n > 5) throw new Error('Enter a whole number from 0 to 5 (0 means no minimum).')
    await write((cfg) => ({ ...cfg, min_each: n }))
  }

  const days = (field: 'due_days' | 'revision_days' | 'review_hours', max: number) => async (value: string) => {
    const n = Number(value)
    if (value.trim() === '' || !Number.isInteger(n) || n < 0 || n > max) throw new Error(`Enter a whole number from 0 to ${max}.`)
    await write((cfg) => ({ ...cfg, [field]: n }))
  }

  const move = (index: number, by: number) =>
    run(
      setCriteria((list) => {
        const to = index + by
        if (to < 0 || to >= list.length) return list
        const copy = [...list]
        ;[copy[index], copy[to]] = [copy[to], copy[index]]
        return copy
      }),
    )

  return (
    <div className={styles.editor}>
      <AutosaveField
        label="Scenario"
        multiline
        rows={6}
        value={text(config.scenario)}
        disabled={disabled}
        onSave={(v) => write((cfg) => ({ ...cfg, scenario: v }))}
        hint="What the learner is asked to do. They see this, so write it to them."
      />
      <AutosaveField
        label="What to hand in"
        multiline
        rows={3}
        value={text(config.handin)}
        disabled={disabled}
        onSave={(v) => write((cfg) => ({ ...cfg, handin: v }))}
        hint="Optional: the format or the evidence you expect."
      />

      <fieldset className={styles.rubric} disabled={disabled}>
        <legend>Rubric</legend>
        <p className={styles.hint}>
          Each criterion is scored 1 to 5 by a mentor. “What it looks at” is shown to learners; “Guidance
          for raters” is only ever shown to raters (what a 1, a 3 and a 5 look like).
        </p>
        {criteria.length === 0 && <p className={styles.warn}>Add at least one criterion — it can’t be published without one.</p>}
        <ol className={styles.list}>
          {criteria.map((c, i) => (
            <li key={c.key} className={styles.criterion}>
              <AutosaveField
                label={`Criterion ${i + 1}`}
                value={c.label}
                required
                disabled={disabled}
                onSave={(v) => patch(c.key, 'label', v)}
              />
              <AutosaveField
                label="What it looks at"
                value={c.description}
                disabled={disabled}
                onSave={(v) => patch(c.key, 'description', v)}
              />
              <AutosaveField
                label="Guidance for raters"
                multiline
                rows={3}
                value={c.guidance}
                disabled={disabled}
                onSave={(v) => patch(c.key, 'guidance', v)}
              />
              <div className={styles.rowActions}>
                <button type="button" className="btn btn-ghost btn-sm" disabled={disabled || i === 0} onClick={() => move(i, -1)}>
                  Move up
                </button>
                <button type="button" className="btn btn-ghost btn-sm" disabled={disabled || i === criteria.length - 1} onClick={() => move(i, 1)}>
                  Move down
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={disabled}
                  onClick={() => run(setCriteria((list) => list.filter((x) => x.key !== c.key)))}
                >
                  Remove criterion {i + 1}
                </button>
              </div>
            </li>
          ))}
        </ol>
        <button
          type="button"
          className="btn btn-sm"
          disabled={disabled || criteria.length >= MAX_CRITERIA}
          onClick={() =>
            run(setCriteria((list) => [...list, { key: nextKey(list), label: `Criterion ${list.length + 1}`, description: '', guidance: '' }]))
          }
        >
          Add a criterion
        </button>
        {criteria.length >= MAX_CRITERIA && <span className={styles.hint}> At most {MAX_CRITERIA}.</span>}
      </fieldset>

      <div className={styles.row}>
        <div className={styles.number}>
          <AutosaveField
            label="Pass mark (out of 5)"
            type="number"
            value={String(Number((threshold * 5).toFixed(2)))}
            disabled={disabled}
            onSave={savePass}
            hint="The average of the criteria."
          />
        </div>
        <div className={styles.number}>
          <AutosaveField
            label="Lowest score on any criterion"
            type="number"
            value={String(minEach)}
            disabled={disabled}
            onSave={saveMin}
            hint="0 means no minimum."
          />
        </div>
      </div>

      <div className={styles.row}>
        <div className={styles.number}>
          <AutosaveField
            label="Days to hand in"
            type="number"
            value={String(whole(config.due_days, 7))}
            disabled={disabled}
            onSave={days('due_days', 365)}
            hint="From when the learner first opens it. 0 means no deadline."
          />
        </div>
        <div className={styles.number}>
          <AutosaveField
            label="Days to revise"
            type="number"
            value={String(whole(config.revision_days, 3))}
            disabled={disabled}
            onSave={days('revision_days', 365)}
            hint="From when changes are requested. 0 means no deadline."
          />
        </div>
        <div className={styles.number}>
          <AutosaveField
            label="Mentor review target (hours)"
            type="number"
            value={String(whole(config.review_hours, 0))}
            disabled={disabled}
            onSave={days('review_hours', 720)}
            hint="0 uses the platform’s default."
          />
        </div>
      </div>

      <fieldset className={styles.holds} disabled={disabled}>
        <legend>What holds the next lesson</legend>
        {(
          [
            ['submit', 'Handing in the work', 'The next lesson opens once they hand in. The lesson counts as complete when the rating passes.'],
            ['pass', 'Passing the rating', 'The next lesson stays locked until the rating passes.'],
          ] as const
        ).map(([value, label, hint]) => (
          <label key={value} className={styles.check}>
            <input
              type="radio"
              name="holds_next"
              checked={(config.holds_next === 'pass' ? 'pass' : 'submit') === value}
              onChange={() => run(write((cfg) => ({ ...cfg, holds_next: value })))}
            />
            <span>
              {label}
              <span className={styles.hint}>{hint}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <label className={styles.check}>
        <input
          type="checkbox"
          checked={config.allow_files !== false}
          disabled={disabled}
          onChange={(e) => run(write((cfg) => ({ ...cfg, allow_files: e.target.checked })))}
        />
        Learners may attach screenshots or a PDF
      </label>

      <p className={styles.hint}>
        Learners revise from their mentor’s feedback as many times as the deadlines allow. Late work is
        accepted and marked late; nothing completes by itself when a date passes. Until something is
        handed in, an unfinished simulation holds the next lesson up even after its deadline. Preview
        shows learners the task and rubric — nothing is recorded.
      </p>
      {problem && (
        <p role="alert" className={styles.warn}>
          {problem}
        </p>
      )}
    </div>
  )
}
