import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { DataTable, type Column } from '../../components/DataTable'
import { PageState } from '../../components/PageState'
import { useCan } from '../../lib/capabilities'
import { CAN } from '../../lib/capabilityKeys'
import { AdminPage, Toolbar } from './AdminPage'
import { adminApi, type UserRow } from './adminApi'
import { CreateUserDialog } from './CreateUserDialog'
import { accountState, formatWhen } from './format'
import { useRoleOptions } from './useRoles'
import { useDebounced, useQuery } from './useQuery'
import styles from './people.module.css'

function columns(label: (role: string) => string): Column<UserRow>[] {
  return [
  {
    key: 'name',
    header: 'User',
    sort: 'name',
    render: (u) => (
      <span className={styles.person}>
        <strong>{u.name}</strong>
        {u.name !== u.email && <span className={styles.sub}>{u.email}</span>}
      </span>
    ),
  },
  {
    key: 'roles',
    header: 'Roles',
    render: (u) => (u.roles.length ? u.roles.map(label).join(', ') : '—'),
  },
  {
    key: 'state',
    header: 'Status',
    render: (u) => (
      <span className={`${styles.state} ${styles[`state_${accountState(u).toLowerCase()}`]}`}>
        {accountState(u)}
      </span>
    ),
  },
  {
    key: 'login',
    header: 'Last sign-in',
    sort: 'last_login',
    hideOnMobile: true,
    render: (u) => formatWhen(u.last_login),
  },
  ]
}

export function UsersPage() {
  const canCreate = useCan(CAN.manageUsers)
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [ordering, setOrdering] = useState('name')
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const term = useDebounced(search)
  const role = params.get('role') ?? ''
  const roleChoices = useRoleOptions()

  const query = {
    search: term,
    role,
    active: status === 'active' ? 'true' : status === 'inactive' ? 'false' : undefined,
    locked: status === 'locked' ? 'true' : undefined,
    ordering,
    page,
  }
  const users = useQuery(() => adminApi.users(query), JSON.stringify(query))

  function setRole(value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set('role', value)
    else next.delete('role')
    setParams(next, { replace: true })
    setPage(1)
  }

  return (
    <AdminPage
      eyebrow="People"
      title="Users"
      hint="Everyone who can sign in, and what they can do."
      actions={
        canCreate && (
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            Add user
          </button>
        )
      }
    >
      <Toolbar>
        <input
          type="search"
          className="input"
          placeholder="Search by name, email or employee id"
          aria-label="Search users"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
        />
        <select
          className="input"
          aria-label="Role"
          value={role}
          onChange={(e) => setRole(e.target.value)}
        >
          <option value="">All roles</option>
          {roleChoices.options.map((o) => (
            <option key={o.name} value={o.name}>
              {o.label}
            </option>
          ))}
        </select>
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
          <option value="active">Active</option>
          <option value="inactive">Deactivated</option>
          <option value="locked">Locked out</option>
        </select>
      </Toolbar>

      {users.loading ? (
        <PageState kind="loading" />
      ) : users.error || !users.data ? (
        <PageState kind="error" title="Couldn’t load users" onRetry={users.reload}>
          {users.error}
        </PageState>
      ) : (
        <DataTable
          label="Users"
          columns={columns(roleChoices.label)}
          rows={users.data.results}
          rowKey={(u) => u.id}
          rowHref={(u) => `/admin/users/${u.id}`}
          meta={users.data}
          ordering={ordering}
          onOrdering={(o) => {
            setOrdering(o)
            setPage(1)
          }}
          onPage={setPage}
          busy={users.refreshing}
          empty={term || role || status ? 'No users match.' : 'There are no users yet.'}
        />
      )}

      {creating && (
        <CreateUserDialog
          onClose={() => setCreating(false)}
          onCreated={() => {
            users.reload()
          }}
        />
      )}
    </AdminPage>
  )
}
