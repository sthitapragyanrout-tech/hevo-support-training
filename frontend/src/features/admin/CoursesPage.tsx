import { useState } from 'react'

import { DataTable, type Column } from '../../components/DataTable'
import { PageState } from '../../components/PageState'
import { AdminPage, Toolbar } from './AdminPage'
import { adminApi, type CourseRow } from './adminApi'
import { formatWhen } from './format'
import { useDebounced, useQuery } from './useQuery'
import styles from './people.module.css'

const STATUSES = [
  ['draft', 'Draft'],
  ['in_review', 'In review'],
  ['published', 'Published'],
  ['published_with_draft', 'Published, edits in draft'],
  ['archived', 'Archived'],
]

/** Live courses read green; work in progress is amber; the rest are quiet. */
const STATE_STYLE: Record<string, string> = {
  published: 'state_active',
  published_with_draft: 'state_active',
  in_review: 'state_locked',
  draft: 'state_deactivated',
  archived: 'state_deactivated',
}

const COLUMNS: Column<CourseRow>[] = [
  {
    key: 'title',
    header: 'Course',
    render: (c) => (
      <span className={styles.person}>
        <strong>{c.title}</strong>
        <span className={styles.sub}>{c.slug}</span>
      </span>
    ),
  },
  {
    key: 'status',
    header: 'Status',
    render: (c) => (
      <span className={`${styles.state} ${styles[STATE_STYLE[c.status.key] ?? 'state_deactivated']}`}>
        {c.status.label}
      </span>
    ),
  },
  { key: 'versions', header: 'Versions', align: 'end', hideOnMobile: true, render: (c) => c.versions },
  { key: 'by', header: 'Created by', hideOnMobile: true, render: (c) => c.created_by ?? '—' },
  { key: 'created', header: 'Created', hideOnMobile: true, render: (c) => formatWhen(c.created_at) },
]

export function CoursesPage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const term = useDebounced(search)
  const query = { search: term, status, page }
  const courses = useQuery(() => adminApi.courseList(query), JSON.stringify(query))

  return (
    <AdminPage
      eyebrow="Content"
      title="Courses"
      hint="Every course in every state. Authoring happens in Studio."
    >
      <Toolbar>
        <input
          type="search"
          className="input"
          placeholder="Search by title"
          aria-label="Search courses"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
        />
        <select
          className="input"
          aria-label="Status"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value)
            setPage(1)
          }}
        >
          <option value="">Any status</option>
          {STATUSES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Toolbar>
      {courses.loading ? (
        <PageState kind="loading" />
      ) : courses.error || !courses.data ? (
        <PageState kind="error" title="Couldn’t load courses" onRetry={courses.reload}>
          {courses.error}
        </PageState>
      ) : (
        <DataTable
          label="Courses"
          columns={COLUMNS}
          rows={courses.data.results}
          rowKey={(c) => c.id}
          rowHref={(c) => `/admin/courses/${c.id}`}
          meta={courses.data}
          onPage={setPage}
          busy={courses.refreshing}
          empty={term || status ? 'No courses match.' : 'There are no courses yet.'}
        />
      )}
    </AdminPage>
  )
}
