import { useMemo, useState } from 'react'

import { progressApi, type AttemptResult } from '../../../lib/api'
import { useCourse } from '../courseContext'
import { pluralize } from '../treeUtils'
import { ActivityShell } from './ActivityShell'
import styles from './QuizActivity.module.css'
import { QuizResults } from './QuizResults'
import { QuizRun } from './QuizRun'
import { parseQuestions, percent } from './quizTypes'
import type { RendererProps } from './types'

type View = 'closed' | 'run' | 'results'

/** Take the quiz one question at a time; the server judges it. Passing
 * completes the activity. Using every attempt without a pass finishes it too —
 * grayed out, the lesson free to continue, every score kept. Sits in the same
 * activity frame as every other type. */
export function QuizActivity({ activity }: RendererProps) {
  const { progress, preview } = useCourse()
  const questions = useMemo(() => parseQuestions(activity.config), [activity.config])
  const passMark =
    typeof activity.config.pass_threshold === 'number' ? activity.config.pass_threshold : 0.7

  const state = progress.activities[activity.id]
  const passed = state === 'completed'
  const exhausted = state === 'exhausted'
  const summary = progress.attempts[activity.id]
  const attemptsLeft: number | null = summary
    ? summary.attempts_left
    : activity.max_attempts > 0
      ? activity.max_attempts
      : null
  const canTryAgain = !passed && !exhausted && attemptsLeft !== 0

  const [view, setView] = useState<View>('closed')
  const [picks, setPicks] = useState<number[][]>(() => questions.map(() => []))
  const [result, setResult] = useState<AttemptResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const canRecord = progress.available && !preview

  const requirement = activity.is_required ? 'Required' : 'Optional'
  const tries = summary ? pluralize(summary.count, 'attempt') : null
  const meta = passed
    ? `Quiz · Passed · best ${percent(summary?.best_score ?? 1)} · ${requirement}`
    : exhausted
      ? `Quiz · Not passed · best ${percent(summary?.best_score ?? 0)} · all attempts used · ${requirement}`
      : summary
        ? [
            'Quiz',
            `Best ${percent(summary.best_score)}`,
            attemptsLeft === null ? tries : `${pluralize(attemptsLeft, 'attempt')} left`,
            requirement,
          ].join(' · ')
        : `Quiz · ${pluralize(questions.length, 'question')} · Pass mark ${percent(passMark)} · ${requirement}`

  function choose(question: number, choice: number, multiple: boolean) {
    setPicks((current) =>
      current.map((p, i) => {
        if (i !== question) return p
        if (!multiple) return [choice]
        return p.includes(choice) ? p.filter((c) => c !== choice) : [...p, choice].sort()
      }),
    )
  }

  function start() {
    setResult(null)
    setProblem(null)
    setPicks(questions.map(() => []))
    setView('run')
  }

  async function submit() {
    setBusy(true)
    setProblem(null)
    try {
      setResult(await progress.submitAttempt(activity.id, picks))
      setView('results')
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  /** Reopen the latest try's results, fetched on demand (it may be from an
   * earlier visit). */
  async function viewResults() {
    setProblem(null)
    if (result) return setView('results')
    setBusy(true)
    try {
      const report = await progressApi.attempts(activity.id)
      if (!report.latest) return setProblem('There are no attempts to show yet.')
      setResult(report.latest)
      setView('results')
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t load your results.')
    } finally {
      setBusy(false)
    }
  }

  async function reset() {
    setProblem(null)
    try {
      await progress.resetAttempts(activity.id)
      setResult(null)
      setPicks(questions.map(() => []))
      setView('closed')
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t reset the attempts.')
    }
  }

  const panel =
    view === 'run' ? (
      <QuizRun
        activityId={activity.id}
        questions={questions}
        picks={picks}
        onPick={choose}
        onSubmit={() => void submit()}
        busy={busy}
        canRecord={canRecord}
        preview={preview}
        problem={problem}
      />
    ) : view === 'results' && result ? (
      <QuizResults
        result={result}
        questions={questions}
        passMark={passMark}
        canTryAgain={canTryAgain}
        bestScore={summary?.best_score ?? result.score}
        onTryAgain={start}
      />
    ) : problem ? (
      <p role="alert" className={styles.problem}>
        {problem}
      </p>
    ) : null

  const hasAttempts = Boolean(summary)

  return (
    <ActivityShell
      icon="quiz"
      title={activity.title}
      meta={meta}
      done={passed}
      muted={exhausted}
      panel={panel}
    >
      {view !== 'closed' ? (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          aria-expanded="true"
          onClick={() => setView('closed')}
        >
          Close
        </button>
      ) : (
        <>
          {passed && <span className={styles.passed}>Passed</span>}
          {exhausted && <span className={styles.none}>Not passed</span>}
          {hasAttempts && !preview && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={busy}
              onClick={() => void viewResults()}
            >
              View results
            </button>
          )}
          {progress.canResetAttempts && hasAttempts && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              title="Clears your attempts so you can take this quiz again"
              onClick={() => void reset()}
            >
              Reset attempts
            </button>
          )}
          {canTryAgain && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={questions.length === 0}
              onClick={start}
            >
              {hasAttempts ? 'Try again' : 'Start quiz'}
            </button>
          )}
        </>
      )}
    </ActivityShell>
  )
}
