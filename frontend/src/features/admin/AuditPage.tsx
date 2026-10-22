import { useState } from 'react'

import { DataTable, type Column } from '../../components/DataTable'
import { PageState } from '../../components/PageState'
import { AdminPage, Toolbar } from './AdminPage'
import { adminApi, type AuditEntry } from './adminApi'
import { actionLabel, formatDateTime } from './format'
import { useDebounced, useQuery } from './useQuery'
import styles from './results.module.css'

/** The changes as short readable pairs; secrets are already hidden server-side. */
function details(changes: Record<string, unknown>): string {
  return Object.entries(changes)
    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join(' · ')
}

const COLUMNS: Column<AuditEntry>[] = [
  { key: 'when', header: 'When', render: (e) => formatDateTime(e.created_at) },
  { key: 'who', header: 'Who', render: (e) => e.actor },
  { key: 'action', header: 'Action', render: (e) => actionLabel(e.action) },
  {
    key: 'target',
    header: 'Target',
    hideOnMobile: true,
    render: (e) => (
      <span className={styles.person}>
        <span>{e.target || '—'}</span>
        {Object.keys(e.changes).length > 0 && <span className={styles.sub}>{details(e.changes)}</span>}
      </span>
    ),
  },
]

export function AuditPage() {
  const [search, setSearch] = useState('')
  const [action, setAction] = useState('')
  const [page, setPage] = useState(1)
  const term = useDebounced(search)

  const actions = useQuery(() => adminApi.auditActions(), 'audit-actions')
  const query = { search: term, action, page }
  const entries = useQuery(() => adminApi.audit(query), JSON.stringify(query))

  return (
    <AdminPage eyebrow="Activity" title="Audit log" hint="Every change made from the console, newest first.">
      <Toolbar>
        <input
          type="search"
          className={`input ${styles.search}`}
          placeholder="Search by person, target or action"
          aria-label="Search the audit log"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
        />
        <select
          className="input"
          aria-label="Action"
          value={action}
          onChange={(e) => {
            setAction(e.target.value)
            setPage(1)
          }}
        >
          <option value="">All actions</option>
          {actions.data?.results.map((a) => (
            <option key={a} value={a}>
              {actionLabel(a)}
            </option>
          ))}
        </select>
      </Toolbar>
      {entries.loading ? (
        <PageState kind="loading" />
      ) : entries.error || !entries.data ? (
        <PageState kind="error" title="Couldn’t load the audit log" onRetry={entries.reload}>
          {entries.error}
        </PageState>
      ) : (
        <DataTable
          label="Audit log"
          columns={COLUMNS}
          rows={entries.data.results}
          rowKey={(e) => e.id}
          meta={entries.data}
          onPage={setPage}
          busy={entries.refreshing}
          empty={term || action ? 'No entries match.' : 'Nothing has been logged yet.'}
        />
      )}
    </AdminPage>
  )
}
