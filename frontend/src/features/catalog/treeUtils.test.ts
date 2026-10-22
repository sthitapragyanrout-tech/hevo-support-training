import { describe, expect, it } from 'vitest'

import { sampleCourse } from './testData'
import {
  firstIncompleteLesson,
  flattenLessons,
  formatMinutes,
  getModules,
  lessonActivities,
  lessonMinutes,
  lessonNeighbors,
  resolveLessonTarget,
  searchLessons,
  summarize,
  totalMinutes,
} from './treeUtils'

describe('getModules: Course → Module → Lesson (+ Sections)', () => {
  const modules = getModules(sampleCourse)

  it('maps segments to numbered modules and topics to lessons', () => {
    expect(modules.map((m) => [m.number, m.node.title])).toEqual([
      [1, 'Fundamentals'],
      [2, 'Troubleshooting'],
    ])
    expect(modules[0].lessons.map((l) => l.node.title)).toEqual(['Pipelines'])
    expect(modules[1].lessons.map((l) => l.node.title)).toEqual(['Failures'])
  })

  it('keeps subtopics as sections inside their lesson, not as lessons', () => {
    const pipelines = modules[0].lessons[0]
    expect(pipelines.sections.map((s) => s.title)).toEqual(['Sources', 'Ingestion'])
    expect(flattenLessons(modules)).toHaveLength(2)
  })

  it('numbers lessons across the whole course in order', () => {
    expect(flattenLessons(modules).map((l) => l.position)).toEqual([1, 2])
    expect(modules[1].lessons[0].moduleNumber).toBe(2)
  })

  it('a module with no lessons yields an empty list', () => {
    const empty = { ...sampleCourse, children: [{ ...sampleCourse.children[0], children: [] }] }
    expect(getModules(empty)[0].lessons).toEqual([])
  })

  it('a lesson without sections is still a lesson', () => {
    const lonely = {
      ...sampleCourse,
      children: [
        {
          ...sampleCourse.children[0],
          children: [{ ...sampleCourse.children[0].children[0], children: [] }],
        },
      ],
    }
    const [lesson] = getModules(lonely)[0].lessons
    expect(lesson.sections).toEqual([])
  })
})

describe('lesson helpers', () => {
  const lessons = flattenLessons(getModules(sampleCourse))

  it('lessonActivities collects the lesson’s own and every section’s', () => {
    expect(lessonActivities(lessons[0]).map((a) => a.title)).toEqual([
      'Read the docs',
      'Sources quiz',
      'Ingestion walkthrough',
    ])
    expect(lessonActivities(lessons[1])).toEqual([])
  })

  it('lessonMinutes sums sections unless the lesson sets its own', () => {
    expect(lessonMinutes(lessons[0])).toBe(33)
    const own = { ...lessons[0], node: { ...lessons[0].node, estimated_minutes: 20 } }
    expect(lessonMinutes(own)).toBe(20)
    expect(lessonMinutes({ ...lessons[0], sections: [] })).toBeNull()
  })

  it('totalMinutes adds lessons and is null when nothing is estimated', () => {
    expect(totalMinutes(lessons)).toBe(45)
    expect(totalMinutes([])).toBeNull()
  })
})

describe('navigation helpers', () => {
  const modules = getModules(sampleCourse)
  const lessons = flattenLessons(modules)

  it('lessonNeighbors returns previous/next across module boundaries', () => {
    expect(lessonNeighbors(lessons, 3)).toEqual({ previous: null, next: lessons[1] })
    expect(lessonNeighbors(lessons, 7)).toEqual({ previous: lessons[0], next: null })
    expect(lessonNeighbors(lessons, 999)).toEqual({ previous: null, next: null })
  })

  it('resolveLessonTarget sends a module to its first lesson and a section to its lesson', () => {
    expect(resolveLessonTarget(modules, 2)).toEqual({ lessonId: 3, sectionId: null })
    expect(resolveLessonTarget(modules, 5)).toEqual({ lessonId: 3, sectionId: 5 })
    expect(resolveLessonTarget(modules, 999)).toBeNull()
  })

  it('firstIncompleteLesson skips completed lessons', () => {
    expect(firstIncompleteLesson(lessons, new Set())?.node.id).toBe(3)
    expect(firstIncompleteLesson(lessons, new Set([3]))?.node.id).toBe(7)
    expect(firstIncompleteLesson(lessons, new Set([3, 7]))).toBeNull()
  })
})

describe('formatting and summaries', () => {
  it('formatMinutes', () => {
    expect(formatMinutes(12)).toBe('12 min')
    expect(formatMinutes(60)).toBe('1h')
    expect(formatMinutes(185)).toBe('3h 05m')
  })

  it('summarize returns the first plain paragraph, skipping headings and callouts', () => {
    const md = '## Title\n\n> note\n\nA **bold** [link](http://x) intro.\n\nSecond.'
    expect(summarize(md)).toBe('A bold link intro.')
    expect(summarize('')).toBe('')
    expect(summarize('word '.repeat(100), 20).endsWith('…')).toBe(true)
  })

  it('cuts at a sentence or word boundary, never mid-word, and skips lead-in lines', () => {
    expect(summarize('First sentence here. Second sentence that keeps going and going.', 40)).toBe(
      'First sentence here.',
    )
    const cut = summarize('Alpha beta gamma delta epsilon zeta eta theta iota kappa', 24)
    expect(cut).toBe('Alpha beta gamma delta…')
    expect(summarize('Read these quickly:\n\n1. one\n2. two')).toBe('')
    expect(summarize('> [!SCENARIO] x\n\nThe real intro.')).toBe('The real intro.')
  })
})

describe('searchLessons', () => {
  const modules = getModules(sampleCourse)
  const titles = (q: string) => searchLessons(modules, q).map((l) => l.node.title)

  it('matches the lesson title, its intro, its sections and its module, case-insensitively', () => {
    expect(titles('PIPELINES')).toEqual(['Pipelines'])
    expect(titles('from a to b')).toEqual(['Pipelines']) // lesson intro
    expect(titles('cdc')).toEqual(['Pipelines']) // text inside a section
    expect(titles('ingestion')).toEqual(['Pipelines']) // section title
    expect(titles('troubleshooting')).toEqual(['Failures']) // module title
  })

  it('returns everything for an empty query and nothing for no match', () => {
    expect(searchLessons(modules, '  ')).toHaveLength(2)
    expect(searchLessons(modules, 'zzz')).toEqual([])
  })
})
