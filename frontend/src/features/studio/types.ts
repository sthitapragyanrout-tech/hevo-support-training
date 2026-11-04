export type NodeKind = 'course' | 'segment' | 'topic' | 'subtopic'

export interface AuthActivity {
  id: number
  activity_type: string
  title: string
  config: Record<string, unknown>
  is_required: boolean
  points: number
  max_attempts: number
  mastery_threshold: number | null
  order: number
  needs_setup: boolean
  completable: boolean
}

export interface AuthNode {
  id: number
  kind: NodeKind
  title: string
  slug: string
  description: string
  is_required: boolean
  estimated_minutes: number | null
  order: number
  activities: AuthActivity[]
  children: AuthNode[]
}

export interface CourseStatus {
  key: 'draft' | 'in_review' | 'published' | 'published_with_draft' | 'archived'
  label: string
}

export interface AuthCourseSummary {
  id: number
  slug: string
  title: string
  status: CourseStatus
  /** Present on the list endpoint only. */
  modules?: number
  lessons?: number
}

export interface VersionInfo {
  number: number
  state: string
  published_at: string | null
  submitted_at: string | null
  submitted_by: string | null
}

export interface AuthCourse extends AuthCourseSummary {
  /** How learners move through the course. */
  learning_order?: 'free' | 'sequential'
  version: VersionInfo | null
  published_version: VersionInfo | null
  editable: boolean
  actions: {
    start_draft: boolean
    submit: boolean
    publish: boolean
    return_to_draft: boolean
  }
  tree: { id: number; course_id: number; version: number; root: AuthNode | null } | null
}

export interface ActivityType {
  key: string
  label: string
  description: string
  icon: string
  config_schema: JsonSchema
  default_config: Record<string, unknown>
  renderer_key: string
}

export interface JsonSchema {
  type?: string
  title?: string
  properties?: Record<string, JsonSchema>
  required?: string[]
  minimum?: number
  maximum?: number
  [key: string]: unknown
}

export interface ChecklistIssue {
  message: string
  node_id: number | null
  level: 'error' | 'warning'
}

export interface ChecklistResult {
  ok: boolean
  issues: ChecklistIssue[]
}

export interface ImportMessage {
  row: number | null
  message: string
}

export interface ImportOutlineNode {
  title: string
  level: 'module' | 'lesson' | 'section'
  activities: { type: string; title: string }[]
  children: ImportOutlineNode[]
}

export interface ImportPreview {
  headers: string[]
  mapping: Record<string, string | null>
  counts: { modules: number; lessons: number; sections: number; activities: number }
  outline: ImportOutlineNode[]
  errors: ImportMessage[]
  warnings: ImportMessage[]
  ok: boolean
}

/** What authors call each level (the data model calls them segment/topic/subtopic). */
export const KIND_LABEL: Record<NodeKind, string> = {
  course: 'Course',
  segment: 'Module',
  topic: 'Lesson',
  subtopic: 'Section',
}
