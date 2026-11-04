import { ApiError, getCookie, request } from '../../lib/api'
import type {
  ActivityType,
  AuthActivity,
  AuthCourse,
  AuthCourseSummary,
  AuthNode,
  ChecklistResult,
  ImportPreview,
} from './types'
import type { CourseTree } from '../../lib/api'

const BASE = '/api/v1/authoring'

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
})

type NodeFields = Partial<
  Pick<AuthNode, 'title' | 'description' | 'estimated_minutes' | 'is_required'>
>
type ActivityFields = Partial<
  Pick<
    AuthActivity,
    'title' | 'config' | 'is_required' | 'points' | 'max_attempts' | 'mastery_threshold'
  >
>

export const studioApi = {
  activityTypes: () => request<ActivityType[]>(`${BASE}/activity-types/`),
  courses: () => request<AuthCourseSummary[]>(`${BASE}/courses/`),
  createCourse: (title: string, description: string) =>
    request<AuthCourse>(`${BASE}/courses/`, json('POST', { title, description })),
  course: (id: number | string) => request<AuthCourse>(`${BASE}/courses/${id}/`),
  updateOverview: (
    id: number,
    changes: { title?: string; description?: string; learning_order?: 'free' | 'sequential' },
  ) =>
    request<AuthCourse>(`${BASE}/courses/${id}/`, json('PATCH', changes)),
  startDraft: (id: number) => request<AuthCourse>(`${BASE}/courses/${id}/draft/`, json('POST')),
  preview: (id: number | string) => request<CourseTree>(`${BASE}/courses/${id}/preview/`),

  addNode: (courseId: number, parent: number, title: string) =>
    request<AuthNode>(`${BASE}/courses/${courseId}/nodes/`, json('POST', { parent, title })),
  updateNode: (id: number, changes: NodeFields) =>
    request<AuthNode>(`${BASE}/nodes/${id}/`, json('PATCH', changes)),
  deleteNode: (id: number) => request<void>(`${BASE}/nodes/${id}/`, json('DELETE')),
  nodeImpact: (id: number) =>
    request<{ lessons: number; sections: number; activities: number }>(`${BASE}/nodes/${id}/impact/`),
  reorderChildren: (parentId: number, ids: number[]) =>
    request<void>(`${BASE}/nodes/${parentId}/order/`, json('PUT', { ids })),

  addActivity: (nodeId: number, activityType: string) =>
    request<AuthActivity>(
      `${BASE}/nodes/${nodeId}/activities/`,
      json('POST', { activity_type: activityType }),
    ),
  updateActivity: (id: number, changes: ActivityFields) =>
    request<AuthActivity>(`${BASE}/activities/${id}/`, json('PATCH', changes)),
  deleteActivity: (id: number) => request<void>(`${BASE}/activities/${id}/`, json('DELETE')),
  reorderActivities: (nodeId: number, ids: number[]) =>
    request<void>(`${BASE}/nodes/${nodeId}/activities/order/`, json('PUT', { ids })),

  checklist: (id: number) => request<ChecklistResult>(`${BASE}/courses/${id}/publish-checklist/`),
  submit: (id: number) => request<AuthCourse>(`${BASE}/courses/${id}/submit/`, json('POST')),
  publish: (id: number) => request<AuthCourse>(`${BASE}/courses/${id}/publish/`, json('POST')),
  returnToDraft: (id: number) =>
    request<AuthCourse>(`${BASE}/courses/${id}/return-to-draft/`, json('POST')),

  importPreview: (id: number, file: File, mapping?: Record<string, string | null>) =>
    request<ImportPreview>(`${BASE}/courses/${id}/import/preview/`, {
      method: 'POST',
      body: importForm(file, mapping),
    }),
  importCommit: (id: number, file: File, mapping?: Record<string, string | null>) =>
    request<{ counts: ImportPreview['counts']; course: AuthCourse }>(
      `${BASE}/courses/${id}/import/commit/`,
      { method: 'POST', body: importForm(file, mapping) },
    ),
}

/** An uploaded video and where it is in becoming playable. */
export interface MediaAsset {
  id: number
  status: 'uploaded' | 'processing' | 'ready' | 'failed'
  status_label: string
  original_name: string
  size_bytes: number
  duration_seconds: number | null
  width: number | null
  height: number | null
  /** A sentence an author can act on (never a technical message). */
  error: string
  retryable: boolean
  video_url: string | null
  poster_url: string | null
}

export interface MediaLimits {
  max_upload_mb: number
  max_duration_minutes: number
  allowed_extensions: string[]
}

export const mediaApi = {
  limits: () => request<MediaLimits>(`${BASE}/media/limits/`),
  get: (id: number) => request<MediaAsset>(`${BASE}/media/${id}/`),
  retry: (id: number) => request<MediaAsset>(`${BASE}/media/${id}/retry/`, json('POST')),
  /** Upload with real progress (fetch can't report upload progress). */
  upload: (file: File, onProgress: (fraction: number) => void): Promise<MediaAsset> =>
    new Promise((resolve, reject) => {
      const form = new FormData()
      form.append('file', file)
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${BASE}/media/`)
      const token = getCookie('csrftoken')
      if (token) xhr.setRequestHeader('X-CSRFToken', token)
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded / e.total)
      }
      xhr.onerror = () =>
        reject(new ApiError(0, 'The upload was interrupted. Check your connection and try again.'))
      xhr.onload = () => {
        let body: { detail?: string } & Partial<MediaAsset> = {}
        try {
          body = JSON.parse(xhr.responseText)
        } catch {
          // no JSON body
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as MediaAsset)
        else {
          reject(
            new ApiError(
              xhr.status,
              body.detail ??
                (xhr.status === 413
                  ? 'That file is too large.'
                  : 'The upload didn’t work. Please try again.'),
            ),
          )
        }
      }
      xhr.send(form)
    }),
}

function importForm(file: File, mapping?: Record<string, string | null>): FormData {
  const form = new FormData()
  form.append('file', file)
  if (mapping) form.append('mapping', JSON.stringify(mapping))
  return form
}
