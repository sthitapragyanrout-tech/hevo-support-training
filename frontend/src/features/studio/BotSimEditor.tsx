import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { simApi } from '../../lib/api'
import { adminApi, type PracticeOptions } from '../admin/adminApi'
import { AutosaveField } from './AutosaveField'
import type { EditorProps } from './QuizEditor'
import styles from './BotSimEditor.module.css'
import { useConfigWriter } from './useConfigWriter'

const PERSONAS = ['random', 'urgent', 'technical', 'non-technical', 'terse']
const label = (text: string) => text.split(' — ')[0]

/** Set up a practice ticket: who the customer is, what they may ask about, and
 * what it takes to pass. Shows how many approved scenarios match right now — a
 * ticket with none can't be published. */
export function BotSimEditor({ activity, disabled, save }: EditorProps) {
  const config = activity.config
  const persona = typeof config.persona === 'string' ? config.persona : 'random'
  const topics = Array.isArray(config.topics) ? (config.topics as string[]) : []
  const threshold = typeof config.pass_threshold === 'number' ? config.pass_threshold : 0.7
  const exchanges = typeof config.max_exchanges === 'number' ? config.max_exchanges : 6
  const required = typeof config.required_tickets === 'number' ? config.required_tickets : 5
  const requireAverage = config.require_average === true

  const write = useConfigWriter(config, (next) => save({ config: next }))
  const [problem, setProblem] = useState<string | null>(null)
  const [options, setOptions] = useState<PracticeOptions | null>(null)
  const [count, setCount] = useState<number | null>(null)

  useEffect(() => {
    adminApi.practiceOptions().then(setOptions, () => {})
  }, [])

  const topicKey = topics.join(',')
  useEffect(() => {
    let live = true
    simApi.scenarioCount(persona, topicKey ? topicKey.split(',') : []).then(
      (r) => live && setCount(r.count),
      () => live && setCount(null),
    )
    return () => {
      live = false
    }
  }, [persona, topicKey])

  function run(task: Promise<void>) {
    setProblem(null)
    task.catch((err) => setProblem(err instanceof Error ? err.message : 'That didn’t save.'))
  }

  async function savePass(text: string) {
    const value = Number(text)
    if (text.trim() === '' || Number.isNaN(value) || value < 2 || value > 5) {
      throw new Error('Enter a pass mark from 2 to 5 (out of 5).')
    }
    await write((cfg) => ({ ...cfg, pass_threshold: Math.round((value / 5) * 1000) / 1000 }))
  }

  async function saveReplies(text: string) {
    const value = Number(text)
    if (!Number.isInteger(value) || value < 3 || value > 6) throw new Error('Enter a whole number from 3 to 6.')
    await write((cfg) => ({ ...cfg, max_exchanges: value }))
  }

  async function saveRequired(text: string) {
    const value = Number(text)
    if (!Number.isInteger(value) || value < 1 || value > 20) {
      throw new Error('Enter a whole number from 1 to 20.')
    }
    const cap = activity.max_attempts
    if (cap > 0 && value > cap) {
      throw new Error(`Learners may take at most ${cap} tickets, so they couldn’t finish ${value}. Raise that limit first.`)
    }
    await write((cfg) => ({ ...cfg, required_tickets: value }))
  }

  async function saveAttempts(text: string) {
    const tries = Number(text)
    if (text.trim() === '' || !Number.isInteger(tries) || tries < 0) {
      throw new Error('Enter a whole number, or 0 for no limit.')
    }
    if (tries > 0 && tries < required) {
      throw new Error(`Learners must finish ${required} tickets, so the limit can’t be lower than that (or use 0).`)
    }
    await save({ max_attempts: tries })
  }

  const toggleTopic = (key: string) =>
    run(
      write((cfg) => {
        const current = Array.isArray(cfg.topics) ? (cfg.topics as string[]) : []
        return {
          ...cfg,
          topics: current.includes(key) ? current.filter((t) => t !== key) : [...current, key],
        }
      }),
    )

  const tries = activity.max_attempts
  const skips = options?.skips_allowed ?? 5
  return (
    <div className={styles.editor}>
      <div className={styles.row}>
        <div className={styles.field}>
          <label htmlFor={`persona-${activity.id}`}>Customer type</label>
          <select
            id={`persona-${activity.id}`}
            className="input"
            value={persona}
            disabled={disabled}
            onChange={(e) => run(write((cfg) => ({ ...cfg, persona: e.target.value })))}
          >
            {PERSONAS.map((p) => (
              <option key={p} value={p}>
                {p === 'random' ? 'A mix (random)' : p}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.number}>
          <AutosaveField
            label="Tickets to complete"
            type="number"
            value={String(required)}
            disabled={disabled}
            onSave={saveRequired}
            hint="How many finished, scored tickets complete it."
          />
        </div>
        <div className={styles.number}>
          <AutosaveField
            label="Pass mark (out of 5)"
            type="number"
            value={String(Number((threshold * 5).toFixed(2)))}
            disabled={disabled}
            onSave={savePass}
            hint="Feedback on each ticket; it doesn’t decide completion."
          />
        </div>
        <div className={styles.number}>
          <AutosaveField
            label="Replies allowed"
            type="number"
            value={String(exchanges)}
            disabled={disabled}
            onSave={saveReplies}
            hint="3 to 6 replies per ticket."
          />
        </div>
        <div className={styles.number}>
          <AutosaveField
            label="Most tickets allowed"
            type="number"
            value={String(tries)}
            disabled={disabled}
            onSave={saveAttempts}
            hint="0 means no limit."
          />
        </div>
      </div>

      <label className={styles.check}>
        <input
          type="checkbox"
          checked={requireAverage}
          disabled={disabled}
          onChange={(e) => run(write((cfg) => ({ ...cfg, require_average: e.target.checked })))}
        />
        Also require the average of the last {required} to reach the pass mark
      </label>
      <p className={styles.hint}>
        Off by default: this is practice, so finishing {required} tickets completes it whatever they scored.
      </p>

      <fieldset className={styles.topics} disabled={disabled}>
        <legend>Topics</legend>
        <p className={styles.hint}>Leave all unticked to allow any topic.</p>
        <div className={styles.topicGrid}>
          {(options?.topics ?? []).map((t) => (
            <label key={t.key} className={styles.check}>
              <input type="checkbox" checked={topics.includes(t.key)} onChange={() => toggleTopic(t.key)} />
              {label(t.label)}
            </label>
          ))}
        </div>
      </fieldset>

      <p
        className={count !== null && count < required ? styles.warn : styles.hint}
        role={count !== null && count < required ? 'alert' : 'status'}
      >
        {count === null
          ? 'Checking available scenarios…'
          : count === 0
            ? 'No approved scenarios match these settings, so this can’t be published yet. '
            : count < required
              ? `Only ${count} approved scenario${count === 1 ? '' : 's'} match, but learners must finish ${required} — this can’t be published yet. `
              : `${count} approved scenario${count === 1 ? '' : 's'} match these settings. `}
        {count !== null && count >= required && count < required + skips
          ? `Learners may skip up to ${skips}, so one who skips a lot could run out of new questions. `
          : ''}
        <Link to="/admin/practice">Practice scenarios</Link>
        {' · '}Use Preview to try the ticket yourself — nothing is scored.
      </p>

      {problem && (
        <p role="alert" className={styles.warn}>
          {problem}
        </p>
      )}
    </div>
  )
}
