import { useState } from 'react'

import { Icon } from '../../components/Icon'
import { AutosaveField } from './AutosaveField'
import { useConfigWriter } from './useConfigWriter'
import { ConfirmDialog } from './ConfirmDialog'
import styles from './QuizEditor.module.css'
import {
  addChoice,
  correctChoices,
  isMultiple,
  moveItemSafe,
  newQuestion,
  readQuestions,
  removeAt,
  removeChoice,
  replaceAt,
  setCorrect,
  setMultiple,
  type QuizQuestion,
} from './quizModel'
import type { studioApi } from './studioApi'
import type { AuthActivity } from './types'

export interface EditorProps {
  activity: AuthActivity
  disabled: boolean
  /** Persist changes to the activity; rejects with a readable message. */
  save: (changes: Parameters<typeof studioApi.updateActivity>[1]) => Promise<void>
}

/** Build a quiz with plain fields — questions, choices, which are correct —
 * instead of the generic settings form. Every field saves as you leave it. */
export function QuizEditor({ activity, disabled, save }: EditorProps) {
  const config = activity.config
  const questions = readQuestions(config)
  const [removing, setRemoving] = useState<number | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  const threshold = typeof config.pass_threshold === 'number' ? config.pass_threshold : 0.7

  // Edits build on the latest working copy, so two quick edits both survive.
  const write = useConfigWriter(config, (next) => save({ config: next }))
  const editQuestions = (change: (list: QuizQuestion[]) => QuizQuestion[]) =>
    write((cfg) => ({ ...cfg, questions: change(readQuestions(cfg)) }))
  const edit = (index: number, change: (q: QuizQuestion) => QuizQuestion) =>
    editQuestions((list) => replaceAt(list, index, change(list[index])))

  /** Button-driven edits have no field to show a failure in, so say it here. */
  function run(task: Promise<void>) {
    setProblem(null)
    task.catch((err) =>
      setProblem(err instanceof Error ? err.message : 'That didn’t save. Please try again.'),
    )
  }

  async function savePassMark(text: string) {
    const percent = Number(text)
    if (text.trim() === '' || Number.isNaN(percent) || percent < 0 || percent > 100) {
      throw new Error('Enter a percentage from 0 to 100.')
    }
    await write((cfg) => ({ ...cfg, pass_threshold: percent / 100 }))
  }

  async function saveAttempts(text: string) {
    const tries = Number(text)
    if (text.trim() === '' || !Number.isInteger(tries) || tries < 0) {
      throw new Error('Enter a whole number, or 0 for unlimited.')
    }
    await save({ max_attempts: tries })
  }

  return (
    <div className={styles.editor}>
      <div className={styles.settings}>
        <div className={styles.number}>
          <AutosaveField
            label="Pass mark (%)"
            type="number"
            value={String(Math.round(threshold * 100))}
            disabled={disabled}
            onSave={savePassMark}
            hint="Share of questions to get right."
          />
        </div>
        <div className={styles.number}>
          <AutosaveField
            label="Attempts allowed"
            type="number"
            value={String(activity.max_attempts)}
            disabled={disabled}
            onSave={saveAttempts}
            hint="0 means unlimited tries."
          />
        </div>
      </div>

      {questions.length === 0 && (
        <p className={styles.empty}>No questions yet. Add the first one below.</p>
      )}

      <ol className={styles.questions}>
        {questions.map((q, i) => (
          <li key={i} className={styles.question}>
            <div className={styles.head}>
              <h5 className={styles.number_}>Question {i + 1}</h5>
              {!disabled && (
                <div className={styles.tools}>
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label={`Move question ${i + 1} up`}
                    disabled={i === 0}
                    onClick={() => run(editQuestions((list) => moveItemSafe(list, i, i - 1)))}
                  >
                    <Icon name="arrowUp" size={14} />
                  </button>
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label={`Move question ${i + 1} down`}
                    disabled={i === questions.length - 1}
                    onClick={() => run(editQuestions((list) => moveItemSafe(list, i, i + 1)))}
                  >
                    <Icon name="arrowDown" size={14} />
                  </button>
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label={`Delete question ${i + 1}`}
                    onClick={() =>
                      q.text.trim() || q.choices.some((c) => c.trim())
                        ? setRemoving(i)
                        : run(editQuestions((list) => removeAt(list, i)))
                    }
                  >
                    <Icon name="trash" size={14} />
                  </button>
                </div>
              )}
            </div>

            <AutosaveField
              label={`Question ${i + 1} text`}
              hideLabel
              compact
              multiline
              rows={2}
              value={q.text}
              placeholder="What do you want to ask?"
              disabled={disabled}
              onSave={(text) => edit(i, (cur) => ({ ...cur, text }))}
            />

            <fieldset className={styles.choices} disabled={disabled}>
              <legend className={styles.legend}>
                Choices — {isMultiple(q) ? 'tick every correct one' : 'pick the correct one'}
              </legend>
              {q.choices.map((choice, c) => (
                <div key={c} className={styles.choice}>
                  <input
                    type={isMultiple(q) ? 'checkbox' : 'radio'}
                    name={`correct-${activity.id}-${i}`}
                    className={styles.marker}
                    aria-label={`Choice ${c + 1} is correct`}
                    checked={correctChoices(q).includes(c)}
                    onChange={(e) => run(edit(i, (cur) => setCorrect(cur, c, e.target.checked)))}
                  />
                  <div className={styles.grow}>
                    <AutosaveField
                      label={`Choice ${c + 1} of question ${i + 1}`}
                      hideLabel
                      compact
                      value={choice}
                      placeholder={`Choice ${c + 1}`}
                      disabled={disabled}
                      onSave={(text) =>
                        edit(i, (cur) => ({ ...cur, choices: replaceAt(cur.choices, c, text) }))
                      }
                    />
                  </div>
                  {!disabled && (
                    <button
                      type="button"
                      className="icon-btn"
                      aria-label={`Remove choice ${c + 1} of question ${i + 1}`}
                      disabled={q.choices.length <= 2}
                      onClick={() => run(edit(i, (cur) => removeChoice(cur, c)))}
                    >
                      <Icon name="close" size={14} />
                    </button>
                  )}
                </div>
              ))}
            </fieldset>

            {!disabled && (
              <div className={styles.row}>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => run(edit(i, addChoice))}
                >
                  <Icon name="plus" size={14} /> Add choice
                </button>
                <label className={styles.check}>
                  <input
                    type="checkbox"
                    checked={isMultiple(q)}
                    onChange={(e) => run(edit(i, (cur) => setMultiple(cur, e.target.checked)))}
                  />
                  More than one correct answer
                </label>
              </div>
            )}

            <AutosaveField
              label="Explanation (optional)"
              multiline
              rows={2}
              compact
              value={q.explanation ?? ''}
              placeholder="Shown to the learner after they pass."
              disabled={disabled}
              onSave={(explanation) =>
                edit(i, (cur) => {
                  const { explanation: _old, ...rest } = cur
                  return explanation.trim() ? { ...rest, explanation } : rest
                })
              }
            />
          </li>
        ))}
      </ol>

      {problem && (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      )}

      {!disabled && (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => run(editQuestions((list) => [...list, newQuestion()]))}
        >
          <Icon name="plus" size={14} /> Add question
        </button>
      )}

      {removing !== null && (
        <ConfirmDialog
          title={`Delete question ${removing + 1}?`}
          confirmLabel="Delete question"
          onCancel={() => setRemoving(null)}
          onConfirm={() => {
            run(editQuestions((list) => removeAt(list, removing)))
            setRemoving(null)
          }}
        >
          This removes the question and its choices from the quiz.
        </ConfirmDialog>
      )}
    </div>
  )
}
