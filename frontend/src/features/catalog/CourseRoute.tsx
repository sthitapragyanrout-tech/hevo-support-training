import { useMemo, type ReactNode } from 'react'
import { Link, Outlet, useParams } from 'react-router-dom'

import { PageState } from '../../components/PageState'
import styles from './CourseRoute.module.css'
import { catalogApi, type CourseTree } from '../../lib/api'
import type { CourseContext } from './courseContext'
import { flattenLessons, getModules } from './treeUtils'
import { useAsync } from './useAsync'
import { useProgress } from './useProgress'

interface BaseProps {
  /** How to load the course tree for the URL's `:courseId` param. */
  load: (id: string) => Promise<CourseTree>
  /** URL prefix for links inside the course (see CourseContext.basePath). */
  basePathFor: (id: string, tree: CourseTree) => string
  preview: boolean
  /** Shown above the course screens (the author's "previewing a draft" bar). */
  banner?: ReactNode
  backTo: { to: string; label: string }
}

/** Loads one course tree and shares it with the landing and lesson routes,
 * so moving between them doesn't refetch. Used for learners and — with a
 * different loader and base path — for an author's preview of a draft. */
export function CourseRouteBase({ load, basePathFor, preview, banner, backTo }: BaseProps) {
  const { courseId = '' } = useParams()
  const { data, loading, errorStatus, error, reload } = useAsync(() => load(courseId), courseId)
  // Real progress for learners; inert in an author's preview of a draft.
  const progress = useProgress(data?.id ?? null, !preview)

  // The course's shape depends only on the loaded tree; progress changes must
  // never rebuild it (lesson identity is what pages key their effects on).
  const structure = useMemo(() => {
    if (!data?.root) return null
    const modules = getModules(data.root)
    return { root: data.root, modules, lessons: flattenLessons(modules) }
  }, [data])

  const context = useMemo<CourseContext | null>(() => {
    if (!data || !structure) return null
    return {
      courseId: data.id,
      basePath: basePathFor(courseId, data),
      preview,
      ...structure,
      progress,
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, structure, progress, courseId, preview])

  if (loading) return <PageState kind="loading" />
  if (errorStatus === 404 || (data && !data.root)) {
    return (
      <PageState kind="empty" title="Course not found">
        {preview ? 'There’s nothing to preview yet. ' : 'It may have been unpublished. '}
        <Link to={backTo.to}>{backTo.label}</Link>
      </PageState>
    )
  }
  if (error || !context) {
    return (
      <PageState kind="error" title="Couldn’t load this course" onRetry={reload}>
        {error}
      </PageState>
    )
  }
  return (
    <>
      {banner}
      {preview && data?.learning_order === 'sequential' && (
        <p className={styles.orderNote} role="note">
          This course is set to <strong>go in order</strong>. Learners will see later lessons locked
          until the ones before them are complete; the preview shows everything open.
        </p>
      )}
      <Outlet context={context} />
    </>
  )
}

/** The learner's course: published versions only. */
export function CourseRoute() {
  return (
    <CourseRouteBase
      load={(id) => catalogApi.course(id)}
      basePathFor={(_, tree) => `/courses/${tree.id}`}
      preview={false}
      backTo={{ to: '/', label: 'Back to your courses' }}
    />
  )
}
