import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { DataTable, type Column } from '../../components/DataTable'
import { PageState } from '../../components/PageState'
import { AdminPage, Toolbar } from './AdminPage'
import { adminApi, type SignInRow } from './adminApi'
import { formatDateTime } from './format'
import { useDebounced, useQuery } from './useQuery'
import styles from './people.module.css'

function columns(failed: boolean): Column<SignInRow>[] {
  return [
    { key: 'when', header: 'When', render: (r) => formatDateTime(r.when) },
    {
      key: 'who',
      header: 'Account',
      render: (r) =>
        r.user_id ? (
          <span className={styles.person}>
            <Link to={`/admin/users/${r.user_id}`}>{r.name}</Link>
            <span className={styles.sub}>{r.username}</span>
          </span>
        ) : (
          <span className={styles.person}>
            <span>{r.username || '—'}</span>
            <span className={styles.sub}>No such account</span>
          </span>
        ),
    },
    { key: 'ip', header: 'Address', render: (r) => r.ip_address ?? '—' },
    {
      key: 'agent',
      header: 'Browser',
      hideOnMobile: true,
      render: (r) => <span className={styles.truncate}>{r.user_agent || '—'}</span>,
    },
    failed
      ? {
          key: 'locked',
          header: 'Result',
          render: (r) => (
            <span className={r.locked_out ? styles.state_locked : styles.sub}>
              {r.locked_out ? 'Locked the account' : 'Refused'}
            </span>
          ),
        }
      : {
          key: 'out',
          header: 'Signed out',
          hideOnMobile: true,
          render: (r) => (r.signed_out_at ? formatDateTime(r.signed_out_at) : '—'),
        },
  ]
}

/** What django-axes records: sign-ins, and the failures behind a lockout. */
export function SignInsPage() {
  const [params] = useSearchParams()
  const [search, setSearch] = useState(params.get('search') ?? '')
  const [kind, setKind] = useState<'success' | 'failed'>('success')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [lockedOnly, setLockedOnly] = useState(false)
  const [page, setPage] = useState(1)
  const term = useDebounced(search)
  const failed = kind === 'failed'

  const query = { search: term, kind, from, to, locked: failed && lockedOnly ? 'true' : undefined, page }
  const rows = useQuery(() => adminApi.signIns(query), JSON.stringify(query))
  const reset = () => setPage(1)

  return (
    <AdminPage
      eyebrow="People"
      title="Sign-in activity"
      hint="Who signed in, who was refused, and what locked an account."
    >
      <Toolbar>
        <select
          className="input"
          aria-label="Show"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value as 'success' | 'failed')
            reset()
          }}
        >
          <option value="success">Sign-ins</option>
          <option value="failed">Failed attempts</option>
        </select>
        <input
          type="search"
          className="input"
          placeholder="Search by account, address or browser"
          aria-label="Search sign-in activity"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            reset()
          }}
        />
        <label className={styles.inline}>
          From
          <input
            type="date"
            className="input"
            value={from}
            onChange={(e) => {
              setFrom(e.target.value)
              reset()
            }}
          />
        </label>
        <label className={styles.inline}>
          To
          <input
            type="date"
            className="input"
            value={to}
            onChange={(e) => {
              setTo(e.target.value)
              reset()
            }}
          />
        </label>
        {failed && (
          <label className={styles.inline}>
            <input
              type="checkbox"
              checked={lockedOnly}
              onChange={(e) => {
                setLockedOnly(e.target.checked)
                reset()
              }}
            />
            Only lockouts
          </label>
        )}
      </Toolbar>

      {rows.loading ? (
        <PageState kind="loading" />
      ) : rows.error || !rows.data ? (
        <PageState kind="error" title="Couldn’t load sign-in activity" onRetry={rows.reload}>
          {rows.error}
        </PageState>
      ) : (
        <DataTable
          label={failed ? 'Failed sign-in attempts' : 'Sign-ins'}
          columns={columns(failed)}
          rows={rows.data.results}
          rowKey={(r) => r.id}
          meta={rows.data}
          onPage={setPage}
          busy={rows.refreshing}
          empty={
            term || from || to || lockedOnly
              ? 'Nothing matches.'
              : failed
                ? 'No failed attempts recorded.'
                : 'No sign-ins recorded yet.'
          }
        />
      )}
    </AdminPage>
  )
}
