import { vi } from 'vitest'

import type { TreeNode } from '../../lib/api'
import { sampleCourse } from './testData'

const QUIZ_ID = 2
const DEFAULT_KEY = [[0], [0, 1]]
const THRESHOLD = 0.5

function courseFor(options: Options): TreeNode {
  const tree = structuredClone(sampleCourse)
  const walk = (n: TreeNode) => {
    for (const a of n.activities) {
      if (a.id === QUIZ_ID) {
        a.is_required = options.quizRequired ?? false
        a.max_attempts = options.quizMaxAttempts ?? 3
      }
    }
    n.children.forEach(walk)
  }
  walk(tree)
  return tree
}

export interface Call {
  method: string
  path: string
}

interface Options {
  /** Lessons already completed / activities already touched when the page loads. */
  completedLessons?: number[]
  activities?: Record<number, 'started' | 'completed'>
  /** Force a failure (status + detail) for `METHOD /path` calls. */
  fail?: Record<string, { status: number; detail: string }>
  courseStatus?: number
  user?: { capabilities: string[] }
  /** Make the sample quiz (activity 2) required, so it gates lesson 3. */
  quizRequired?: boolean
  /** The quiz's answer key (one list of correct choices per question) and
   * try limit (0 = unlimited). The key stays inside this fake "server". */
  quizKey?: number[][]
  quizMaxAttempts?: number
  /** Let the learner reset their own quiz attempts (the dev-only switch). */
  canReset?: boolean
}

const USER = {
  id: 1,
  username: 'learner',
  email: 'learner@example.com',
  employee_id: null,
  must_change_password: false,
  roles: ['learner'],
  capabilities: [] as string[],
}

/** A small stand-in for the learner API (auth + catalog + progress) that
 * remembers what was recorded, so flows can be tested end to end. The one
 * server rule it mirrors: lesson 3 can't complete until reading 1 is done. */
export function mockLearnerApi(options: Options = {}) {
  const calls: Call[] = []
  const completed = new Set(options.completedLessons ?? [])
  const activities: Record<number, string> = { ...(options.activities ?? {}) }
  const attempts: { score: number; correct: number; passed: boolean; picks: number[][] }[] = []
  const key = options.quizKey ?? DEFAULT_KEY
  const limit = options.quizMaxAttempts ?? 3
  const tree = courseFor(options)

  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = (init.method ?? 'GET').toUpperCase()
      const path = url.split('?')[0]
      calls.push({ method, path })
      const reply = (status: number, body: unknown) => ({
        ok: status >= 200 && status < 300,
        status,
        statusText: 'x',
        json: async () => body ?? {},
      })

      const forced = options.fail?.[`${method} ${path}`]
      if (forced) return reply(forced.status, { detail: forced.detail })

      if (path.includes('/auth/session/')) {
        return reply(200, { authenticated: true, user: { ...USER, ...options.user } })
      }
      if (path === '/api/v1/catalog/courses/') {
        return reply(200, [
          {
            id: 1,
            course_id: 1,
            title: 'CX Onboarding',
            description: 'Learn the platform.',
            version: 1,
            published_at: null,
          },
        ])
      }
      if (path === '/api/v1/catalog/courses/1/') {
        return options.courseStatus && options.courseStatus !== 200
          ? reply(options.courseStatus, { detail: 'Not found.' })
          : reply(200, { id: 1, course_id: 1, version: 1, published_at: null, root: tree })
      }
      if (path === '/api/v1/progress/courses/1/') {
        const summary = attempts.length
          ? {
              [QUIZ_ID]: {
                count: attempts.length,
                best_score: Math.max(...attempts.map((a) => a.score)),
                last_score: attempts[attempts.length - 1].score,
                attempts_left: limit ? Math.max(limit - attempts.length, 0) : null,
              },
            }
          : {}
        return reply(200, {
          completed_lessons: [...completed],
          activities,
          attempts: summary,
          can_reset_attempts: options.canReset ?? false,
        })
      }

      const history = () =>
        attempts.map((a, i) => ({
          number: i + 1,
          score: a.score,
          correct: a.correct,
          total: key.length,
          passed: a.passed,
          submitted_at: '2026-10-12T10:00:00Z',
        }))
      const review = (picked: number[][], reveal: boolean) =>
        key.map((k, i) => {
          const ok = [...picked[i]].sort().join() === [...k].sort().join()
          return reveal
            ? { correct: ok, correct_answers: k, explanation: `Because ${i + 1}.` }
            : { correct: ok }
        })

      if (path === `/api/v1/progress/activities/${QUIZ_ID}/attempts/` && method === 'GET') {
        const last = attempts.at(-1)
        if (!last) return reply(200, { history: [], latest: null })
        const finished = ['completed', 'exhausted'].includes(activities[QUIZ_ID])
        return reply(200, {
          history: history(),
          latest: {
            state: activities[QUIZ_ID],
            passed: last.passed,
            score: last.score,
            correct: last.correct,
            total: key.length,
            needed: null,
            attempts_left: limit ? Math.max(limit - attempts.length, 0) : null,
            picks: last.picks,
            review: review(last.picks, finished),
            history: history(),
          },
        })
      }

      if (path === `/api/v1/progress/activities/${QUIZ_ID}/attempts/` && method === 'DELETE') {
        if (!options.canReset) {
          return reply(403, { detail: 'Resetting attempts isn’t available here.' })
        }
        attempts.length = 0
        delete activities[QUIZ_ID]
        if (options.quizRequired) completed.delete(3)
        return reply(204, null)
      }

      if (path === `/api/v1/progress/activities/${QUIZ_ID}/attempts/` && method === 'POST') {
        const picked: number[][] | undefined = JSON.parse(String(init.body ?? '{}')).answers
        const taken = attempts.length
        if (activities[QUIZ_ID] === 'completed') {
          return reply(409, { detail: 'You’ve already passed this one.' })
        }
        if (limit && taken >= limit) {
          return reply(409, {
            detail: 'You’ve used all your attempts. Ask your trainer for another try.',
          })
        }
        if (!picked || picked.length !== key.length || picked.some((p) => p.length === 0)) {
          return reply(400, { detail: 'Answer every question before you submit.' })
        }
        const results = key.map((k, i) => [...picked[i]].sort().join() === [...k].sort().join())
        const correct = results.filter(Boolean).length
        const score = correct / key.length
        const passed = score >= THRESHOLD
        attempts.push({ score, correct, passed, picks: picked })
        const left = limit ? Math.max(limit - attempts.length, 0) : null
        activities[QUIZ_ID] = passed ? 'completed' : left === 0 ? 'exhausted' : 'started'
        return reply(201, {
          state: activities[QUIZ_ID],
          passed,
          score,
          correct,
          total: key.length,
          needed: Math.ceil(THRESHOLD * key.length),
          attempts_left: left,
          picks: picked,
          review: review(picked, passed || left === 0),
          history: history(),
        })
      }

      const activity = path.match(/^\/api\/v1\/progress\/activities\/(\d+)\/(start|complete)\/$/)
      if (activity) {
        const id = Number(activity[1])
        if (id === QUIZ_ID && activity[2] === 'complete') {
          return reply(400, { detail: 'This activity is completed by passing it.' })
        }
        if (activity[2] === 'start') activities[id] ??= 'started'
        else if (method === 'POST') activities[id] = 'completed'
        else {
          if (activities[id]) activities[id] = 'started'
          completed.delete(3) // the server reopens the lesson that needed it
        }
        return reply(200, { state: activities[id] ?? null })
      }

      const lesson = path.match(/^\/api\/v1\/progress\/lessons\/(\d+)\/complete\/$/)
      if (lesson) {
        const id = Number(lesson[1])
        if (method === 'DELETE') {
          completed.delete(id)
          return reply(204, null)
        }
        const pending = [
          ...(activities[1] !== 'completed' ? [1] : []),
          ...(options.quizRequired && !['completed', 'exhausted'].includes(activities[QUIZ_ID])
            ? [QUIZ_ID]
            : []),
        ]
        if (id === 3 && pending.length) {
          return reply(409, {
            detail: `Finish the ${pending.length} required ${pending.length === 1 ? 'activity' : 'activities'} in this lesson first.`,
            pending,
          })
        }
        completed.add(id)
        return reply(200, { completed: true })
      }
      return reply(404, { detail: 'Not found.' })
    }),
  )
  return { calls, completed, activities, attempts }
}
