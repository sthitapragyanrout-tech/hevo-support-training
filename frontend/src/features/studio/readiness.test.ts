import { describe, expect, it } from 'vitest'

import { lessonIssues, readiness } from './readiness'
import type { AuthActivity, AuthNode } from './types'

function node(
  id: number,
  kind: AuthNode['kind'],
  title: string,
  extra: Partial<AuthNode> = {},
  children: AuthNode[] = [],
): AuthNode {
  return {
    id,
    kind,
    title,
    slug: title,
    description: '',
    is_required: true,
    estimated_minutes: null,
    order: 0,
    activities: [],
    children,
    ...extra,
  }
}

const activity = (id: number, needs_setup: boolean): AuthActivity => ({
  id,
  activity_type: 'reading',
  title: 'Reading',
  config: {},
  is_required: true,
  points: 0,
  max_attempts: 3,
  mastery_threshold: null,
  order: 0,
  needs_setup,
  completable: false,
})

describe('readiness (mirrors the server publish checklist)', () => {
  it('asks for a first module on an empty course', () => {
    expect(readiness(node(1, 'course', 'C'))).toEqual([
      { message: 'Add your first module.', nodeId: null },
    ])
  })

  it('flags modules with no lessons and empty lessons', () => {
    const root = node(1, 'course', 'C', {}, [
      node(2, 'segment', 'M1'),
      node(3, 'segment', 'M2', {}, [node(4, 'topic', 'Empty one')]),
    ])
    expect(readiness(root).map((i) => [i.message, i.nodeId])).toEqual([
      ['Module “M1” has no lessons yet.', 2],
      ['Lesson “Empty one” is empty.', 4],
    ])
  })

  it('flags unfinished activities on a lesson and on its sections, pointing at the lesson', () => {
    const lesson = node(4, 'topic', 'L', { description: 'Hook.', activities: [activity(1, true)] }, [
      node(5, 'subtopic', 'S', { activities: [activity(2, true), activity(3, false)] }),
    ])
    const issues = lessonIssues(lesson)
    expect(issues).toHaveLength(2)
    expect(issues.every((i) => i.nodeId === 4)).toBe(true)
    expect(issues[1].message).toContain('in “S”')
  })

  it('is clean when every lesson has content and every activity is set up', () => {
    const root = node(1, 'course', 'C', {}, [
      node(2, 'segment', 'M', {}, [node(3, 'topic', 'L', { description: 'Hook.' })]),
    ])
    expect(readiness(root)).toEqual([])
    expect(readiness(null)).toEqual([])
  })
})
