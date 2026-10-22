import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '../../lib/api'
import { studioApi } from './studioApi'
import type { AuthCourse } from './types'

export interface CourseDetailState {
  course: AuthCourse | null
  loading: boolean
  error: string | null
  notFound: boolean
  /** Re-fetch in the background; the current course stays on screen. */
  refresh: () => Promise<void>
  /** Replace the course with a server response (submit, publish, …). */
  apply: (course: AuthCourse) => void
  /** Optimistic local edit; call `refresh()` afterwards to reconcile. */
  mutate: (change: (course: AuthCourse) => AuthCourse) => void
  reload: () => void
}

/** Loads one course for the builder and keeps it fresh without ever
 * blanking the screen after the first load (so editors keep their focus). */
export function useCourseDetail(courseId: string): CourseDetailState {
  const [course, setCourse] = useState<AuthCourse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const latest = useRef(0)

  const fetchCourse = useCallback(async () => {
    const ticket = ++latest.current
    try {
      const data = await studioApi.course(courseId)
      if (ticket === latest.current) {
        setCourse(data)
        setError(null)
        setNotFound(false)
      }
    } catch (err) {
      if (ticket !== latest.current) return
      if (err instanceof ApiError && err.status === 404) setNotFound(true)
      else setError(err instanceof Error ? err.message : 'Something went wrong.')
    }
  }, [courseId])

  useEffect(() => {
    setLoading(true)
    setCourse(null)
    void fetchCourse().finally(() => setLoading(false))
  }, [fetchCourse, attempt])

  return {
    course,
    loading,
    error,
    notFound,
    refresh: fetchCourse,
    apply: setCourse,
    mutate: (change) => setCourse((c) => (c ? change(c) : c)),
    reload: () => setAttempt((n) => n + 1),
  }
}
