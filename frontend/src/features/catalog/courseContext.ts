import { useOutletContext } from 'react-router-dom'

import type { TreeNode } from '../../lib/api'
import type { Progress } from './useProgress'
import type { Lesson, Module } from './treeUtils'

/** Everything the landing and lesson routes need, loaded once by CourseRoute. */
export interface CourseContext {
  courseId: number
  /** URL prefix for links inside this course view: `/courses/7` for learners,
   * a studio preview prefix when an author previews a draft. */
  basePath: string
  /** True when an author is previewing a draft (no progress, banner shown). */
  preview: boolean
  root: TreeNode
  modules: Module[]
  lessons: Lesson[]
  progress: Progress
}

export function useCourse(): CourseContext {
  return useOutletContext<CourseContext>()
}
