import { render, screen } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ActivitySummary, RatedStatus, RatedSummary, TreeNode } from '../../lib/api'
import type { CourseContext } from './courseContext'
import { LessonPage } from './LessonPage'
import { getModules, flattenLessons, pendingRequired, type Lesson } from './treeUtils'
import { INERT_PROGRESS, type Progress } from './useProgress'

const SIM_ID = 14

function node(
  id: number,
  kind: TreeNode['kind'],
  children: TreeNode[] = [],
  activities: ActivitySummary[] = [],
): TreeNode {
  return {
    id,
    kind,
    title: `${kind} ${id}`,
    slug: `n-${id}`,
    description: '',
    is_required: true,
    estimated_minutes: null,
    activities,
    children,
  }
}

const sim = (over: Partial<ActivitySummary> = {}): ActivitySummary => ({
  id: SIM_ID,
  activity_type: 'manual_sim',
  title: 'Customer reply',
  is_required: true,
  points: 0,
  order: 1,
  max_attempts: 0,
  config: {},
  completable: true,
  ...over,
})

function lessonWith(activities: ActivitySummary[]): Lesson {
  const root = node(1, 'course', [node(2, 'segment', [node(3, 'topic', [], activities)])])
  return flattenLessons(getModules(root))[0]
}

const rated = (status: RatedStatus, over: Partial<RatedSummary> = {}): RatedSummary => ({
  status,
  revisions: 1,
  due_at: null,
  overdue: false,
  last_score: null,
  holds_next: 'submit',
  ...over,
})

describe('What stands between a learner and "Mark complete"', () => {
  const lesson = lessonWith([sim()])

  it('counts a simulation that has not been handed in', () => {
    expect(pendingRequired(lesson, {}, {})).toHaveLength(1)
    expect(
      pendingRequired(lesson, { [SIM_ID]: 'started' }, { [SIM_ID]: rated('not_submitted') }),
    ).toHaveLength(1)
  })

  it.each<RatedStatus>(['waiting', 'changes_requested'])(
    'does not count work handed in and %s, when handing in is enough',
    (status) => {
      expect(
        pendingRequired(lesson, { [SIM_ID]: 'started' }, { [SIM_ID]: rated(status) }),
      ).toHaveLength(0)
    },
  )

  it.each<RatedStatus>(['waiting', 'changes_requested'])(
    'still counts work that is %s when only a pass opens the next lesson',
    (status) => {
      const strict = { [SIM_ID]: rated(status, { holds_next: 'pass' }) }
      expect(pendingRequired(lesson, { [SIM_ID]: 'started' }, strict)).toHaveLength(1)
    },
  )

  it('still counts the lesson’s other required activities', () => {
    const other = sim({ id: 15, activity_type: 'reading', title: 'Read' })
    const both = lessonWith([sim(), other])
    const left = pendingRequired(both, { [SIM_ID]: 'started' }, { [SIM_ID]: rated('waiting') })
    expect(left.map((a) => a.id)).toEqual([15])
  })
})

function renderLesson(progress: Partial<Progress>) {
  const root = node(1, 'course', [node(2, 'segment', [node(3, 'topic')])])
  const modules = getModules(root)
  const context = {
    courseId: 1,
    basePath: '/courses/1',
    preview: false,
    root,
    modules,
    lessons: flattenLessons(modules),
    progress: {
      ...INERT_PROGRESS,
      available: true,
      refresh: vi.fn(),
      ...progress,
    },
  } as unknown as CourseContext
  render(
    <MemoryRouter initialEntries={['/courses/1/lessons/3']}>
      <Routes>
        <Route element={<Outlet context={context} />}>
          <Route path="/courses/1/lessons/:nodeId" element={<LessonPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('A lesson moved past while its simulation awaits a rating', () => {
  it('says so, and offers neither "Lesson complete" nor "Mark complete"', () => {
    renderLesson({ awaiting: new Set([3]) })
    expect(
      screen.getByText(/You can move on\. This lesson is complete once your mentor passes/),
    ).toBeInTheDocument()
    expect(screen.queryByText('Lesson complete')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mark complete' })).not.toBeInTheDocument()
  })

  it('shows "Lesson complete" only once it has settled', () => {
    renderLesson({ completed: new Set([3]) })
    expect(screen.getByText('Lesson complete')).toBeInTheDocument()
    expect(screen.queryByText(/You can move on/)).not.toBeInTheDocument()
  })
})
