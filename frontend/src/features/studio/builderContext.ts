import { useOutletContext } from 'react-router-dom'

import type { CourseDetailState } from './useCourseDetail'
import type { ActivityType, AuthCourse } from './types'

export interface BuilderContext extends Omit<CourseDetailState, 'course'> {
  course: AuthCourse
  activityTypes: ActivityType[]
}

export function useBuilder(): BuilderContext {
  return useOutletContext<BuilderContext>()
}
