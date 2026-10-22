import { useEffect, useRef, useState } from 'react'

import { pluralize } from '../treeUtils'
import styles from './QuizActivity.module.css'
import type { Question } from './quizTypes'

interface Props {
  activityId: number
  questions: Question[]
  picks: number[][]
  onPick: (question: number, choice: number, multiple: boolean) => void
  /** Sends the answers; the parent shows the result. */
  onSubmit: () => void
  busy: boolean
  canRecord: boolean
  preview: boolean
  problem: string | null
}

/** One question at a time: answer, Next, … then Submit on the last one.
 * Going Back keeps every answer. */
export function QuizRun({
  activityId,
  questions,
  picks,
  onPick,
  onSubmit,
  busy,
  canRecord,
  preview,
  problem,
}: Props) {
  const [step, setStep] = useState(0)
  const promptRef = useRef<HTMLLegendElement>(null)
  const moved = useRef(false)

  // After Next/Back, bring the new question to a screen-reader's attention.
  useEffect(() => {
    if (moved.current) promptRef.current?.focus()
    moved.current = true
  }, [step])

  const question = questions[step]
  const last = step === questions.length - 1
  const answered = (picks[step] ?? []).length > 0
  const everyAnswered = picks.every((p) => p.length > 0)
  const mine = picks[step] ?? []

  return (
    <div className={styles.run}>
      <p className={styles.step}>
        Question {step + 1} of {questions.length}
        <span className={styles.track} aria-hidden="true">
          <span className={styles.trackFill} style={{ width: `${((step + 1) / questions.length) * 100}%` }} />
        </span>
      </p>

      <fieldset className={styles.question} disabled={busy}>
        <legend ref={promptRef} tabIndex={-1} className={styles.prompt}>
          {question.text}
        </legend>
        {question.multiple && <p className={styles.hint}>Select all that apply.</p>}
        <ul className={styles.choices}>
          {question.choices.map((choice, c) => (
            <li key={c}>
              <label className={styles.choice} data-picked={mine.includes(c) || undefined}>
                <input
                  type={question.multiple ? 'checkbox' : 'radio'}
                  name={`quiz-${activityId}-${step}`}
                  checked={mine.includes(c)}
                  onChange={() => onPick(step, c, question.multiple)}
                />
                <span>{choice}</span>
              </label>
            </li>
          ))}
        </ul>
      </fieldset>

      {problem && (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      )}

      <div className={styles.footer}>
        {step > 0 && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={busy}
            onClick={() => setStep(step - 1)}
          >
            Back
          </button>
        )}
        {last ? (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={!everyAnswered || busy || !canRecord}
            onClick={onSubmit}
          >
            Submit answers
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={!answered}
            onClick={() => setStep(step + 1)}
          >
            Next
          </button>
        )}
        {preview && last && <span className={styles.progress}>Answers aren’t scored in preview.</span>}
        {!preview && last && !everyAnswered && (
          <span className={styles.progress}>
            {pluralize(picks.filter((p) => p.length === 0).length, 'question')} left unanswered
          </span>
        )}
      </div>
    </div>
  )
}
