import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  progressApi,
  type ActivityState,
  type AttemptResult,
  type AttemptSummary,
} from '../../lib/api'

export interface Progress {
  /** False in an author's preview and while loading: nothing is recorded,
   * and the UI falls back to the calm "Not started" presentation. */
  available: boolean
  /** Ids of lessons the learner has completed. Module/course progress is
   * always derived from this. */
  completed: Set<number>
  activities: Record<number, ActivityState>
  /** Tries so far on scored activities (quizzes), by activity id. */
  attempts: Record<number, AttemptSummary>
  /** Show "Reset attempts" (testing only; the server decides). */
  canResetAttempts: boolean
  /** A plain-language problem from the last action, if any. */
  error: string | null
  startActivity: (id: number) => Promise<void>
  completeActivity: (id: number) => Promise<void>
  uncompleteActivity: (id: number) => Promise<void>
  /** Judged by the server; resolves with the result, rejects with a readable message. */
  submitAttempt: (id: number, answers: number[][]) => Promise<AttemptResult>
  /** Forget the learner's tries so the activity can be taken again. */
  resetAttempts: (id: number) => Promise<void>
  completeLesson: (id: number) => Promise<void>
  uncompleteLesson: (id: number) => Promise<void>
  clearError: () => void
}

interface Snapshot {
  versionId: number | null
  completed: Set<number>
  activities: Record<number, ActivityState>
  attempts: Record<number, AttemptSummary>
  canReset: boolean
  loaded: boolean
}

const EMPTY: Snapshot = {
  versionId: null,
  completed: new Set(),
  activities: {},
  attempts: {},
  canReset: false,
  loaded: false,
}

const noop = async () => {}

/** Nothing recorded, nothing possible — used in preview and before data loads. */
export const INERT_PROGRESS: Progress = {
  available: false,
  completed: new Set(),
  activities: {},
  attempts: {},
  canResetAttempts: false,
  error: null,
  startActivity: noop,
  completeActivity: noop,
  uncompleteActivity: noop,
  submitAttempt: () => Promise.reject(new Error('Progress isn’t recorded here.')),
  resetAttempts: noop,
  completeLesson: noop,
  uncompleteLesson: noop,
  clearError: () => {},
}

/** The learner's progress in one published course (by version id). Actions
 * update the screen immediately and are rolled back, with a readable message,
 * if the server says no. Pass `enabled: false` for an author's preview. */
export function useProgress(versionId: number | null, enabled = true): Progress {
  const [raw, setState] = useState<Snapshot>(EMPTY)
  // A snapshot belongs to one course; moving to another starts clean.
  const state = raw.versionId === versionId ? raw : EMPTY
  const [error, setError] = useState<string | null>(null)
  const live = enabled && versionId != null

  const refresh = useCallback(async () => {
    if (versionId == null) return
    const data = await progressApi.course(versionId)
    setState({
      versionId,
      completed: new Set(data.completed_lessons),
      activities: Object.fromEntries(
        Object.entries(data.activities).map(([id, s]) => [Number(id), s]),
      ),
      attempts: Object.fromEntries(
        Object.entries(data.attempts ?? {}).map(([id, a]) => [Number(id), a]),
      ),
      canReset: data.can_reset_attempts === true,
      loaded: true,
    })
  }, [versionId])

  useEffect(() => {
    if (!live) return
    refresh().catch(() => setError('We couldn’t load your progress. Refresh to try again.'))
  }, [live, refresh])

  return useMemo<Progress>(() => {
    if (!live) return INERT_PROGRESS

    async function attempt(
      optimistic: (s: Snapshot) => Snapshot,
      call: () => Promise<unknown>,
      { reconcile }: { reconcile: boolean },
    ) {
      let before: Snapshot | undefined
      setError(null)
      setState((s) => {
        before = s
        return optimistic(s)
      })
      try {
        await call()
        if (reconcile) await refresh()
      } catch (err) {
        if (before) setState(before)
        setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
      }
    }

    const setActivity = (id: number, next: ActivityState | undefined) => (s: Snapshot) => {
      const activities = { ...s.activities }
      if (next) activities[id] = next
      else delete activities[id]
      return { ...s, activities }
    }

    return {
      available: state.loaded,
      completed: state.completed,
      activities: state.activities,
      attempts: state.attempts,
      canResetAttempts: state.canReset,
      error,
      clearError: () => setError(null),
      startActivity: (id) =>
        attempt(
          (s) => (s.activities[id] ? s : setActivity(id, 'started')(s)),
          () => progressApi.startActivity(id),
          { reconcile: false },
        ),
      completeActivity: (id) =>
        attempt(setActivity(id, 'completed'), () => progressApi.completeActivity(id), {
          reconcile: false,
        }),
      // The server may reopen the lesson this activity belonged to, so re-read.
      uncompleteActivity: (id) =>
        attempt(setActivity(id, 'started'), () => progressApi.uncompleteActivity(id), {
          reconcile: true,
        }),
      submitAttempt: async (id, answers) => {
        // No optimistic guess: the server decides whether this passed.
        const result = await progressApi.submitAttempt(id, answers)
        setState((s) => {
          const before = s.attempts[id]
          const attempts = {
            ...s.attempts,
            [id]: {
              count: (before?.count ?? 0) + 1,
              best_score: Math.max(before?.best_score ?? 0, result.score),
              last_score: result.score,
              attempts_left: result.attempts_left,
            },
          }
          return { ...s, attempts, activities: { ...s.activities, [id]: result.state } }
        })
        return result
      },
      resetAttempts: async (id) => {
        await progressApi.resetAttempts(id)
        // The lesson may have been reopened, so take the server's word for it.
        await refresh()
      },
      completeLesson: (id) =>
        attempt(
          (s) => ({ ...s, completed: new Set(s.completed).add(id) }),
          () => progressApi.completeLesson(id),
          { reconcile: false },
        ),
      uncompleteLesson: (id) =>
        attempt(
          (s) => {
            const completed = new Set(s.completed)
            completed.delete(id)
            return { ...s, completed }
          },
          () => progressApi.uncompleteLesson(id),
          { reconcile: false },
        ),
    }
  }, [live, state, error, refresh])
}

/** Has the learner done anything in this course yet? Progress UI (bars,
 * counts, "Continue learning") appears only once the answer is yes. */
export function hasStarted(progress: Progress): boolean {
  return (
    progress.available &&
    (progress.completed.size > 0 || Object.keys(progress.activities).length > 0)
  )
}
