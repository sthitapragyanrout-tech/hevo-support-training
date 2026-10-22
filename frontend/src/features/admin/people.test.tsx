import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, page, renderAt, type Call } from './testHelpers'

const USERS = 'accounts.manage_users'
const ROLES = 'accounts.manage_roles'

afterEach(() => vi.unstubAllGlobals())

const ANN = {
  id: 11,
  name: 'Ann Ames',
  email: 'ann@example.com',
  username: 'ann',
  employee_id: 'E1',
  is_active: true,
  roles: ['learner'],
  last_login: '2026-10-20T10:00:00Z',
  locked: false,
  must_change_password: false,
}
const BOB = {
  ...ANN,
  id: 12,
  name: 'bob@example.com',
  email: 'bob@example.com',
  username: 'bob',
  employee_id: null,
  is_active: false,
  roles: ['trainer', 'mentor'],
  last_login: null,
  locked: false,
  must_change_password: true,
}
const CY = { ...ANN, id: 13, name: 'cy@example.com', email: 'cy@example.com', locked: true }

const DETAIL = {
  ...ANN,
  first_name: 'Ann',
  last_name: 'Ames',
  timezone: 'Asia/Kolkata',
  date_joined: '2026-09-01T10:00:00Z',
  is_staff: false,
  is_superuser: false,
  can_edit_privileges: false,
  is_self: false,
  identities: [{ provider: 'local', external_id: 'ann', email: 'ann@example.com' }],
}

const bodyOf = (calls: Call[], method: string, suffix: string) =>
  calls.filter((c) => c.method === method && c.path.endsWith(suffix))

describe('Users list', () => {
  const routes = (users = [ANN, BOB, CY]) => ({ 'GET /api/v1/admin/users/': page(users) })

  it('shows who they are, their roles and whether they can sign in', async () => {
    mockApi([USERS], routes())
    renderAt('/admin/users')
    const ann = (await screen.findByRole('link', { name: /Ann Ames/ })).closest('tr')!
    expect(ann).toHaveTextContent('Learner')
    expect(ann).toHaveTextContent('Active')
    expect(screen.getByRole('link', { name: /Ann Ames/ })).toHaveAttribute('href', '/admin/users/11')
    const bob = screen.getByRole('link', { name: /bob@example.com/ }).closest('tr')!
    expect(bob).toHaveTextContent('Trainer, Mentor')
    expect(bob).toHaveTextContent('Deactivated')
    expect(screen.getByRole('link', { name: /cy@example.com/ }).closest('tr')).toHaveTextContent('Locked')
  })

  it('searches and filters by role and status', async () => {
    const calls = mockApi([USERS], routes())
    renderAt('/admin/users')
    await screen.findByRole('link', { name: /Ann Ames/ })

    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'trainer' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('role') === 'trainer')).toBe(true))
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'locked' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('locked') === 'true')).toBe(true))
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'inactive' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('active') === 'false')).toBe(true))
    fireEvent.change(screen.getByLabelText('Search users'), { target: { value: 'ames' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('search') === 'ames')).toBe(true))
  })

  it('opens already filtered when you arrive from a role (the Roles screen links here)', async () => {
    const calls = mockApi([USERS], routes([BOB]))
    renderAt('/admin/users?role=trainer')
    await screen.findByRole('link', { name: /bob@example.com/ })
    expect(calls.some((c) => c.query.get('role') === 'trainer')).toBe(true)
    expect(screen.getByLabelText('Role')).toHaveValue('trainer')
  })

  it('says so when nothing matches', async () => {
    mockApi([USERS], routes([]))
    renderAt('/admin/users')
    expect(await screen.findByText('There are no users yet.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search users'), { target: { value: 'zzz' } })
    expect(await screen.findByText('No users match.')).toBeInTheDocument()
  })

  it('a role-manager who is not a user-manager sees Roles but not Users in the rail', async () => {
    mockApi([ROLES], {
      'GET /api/v1/admin/roles/': { roles: [], actions: [] },
    })
    renderAt('/admin')
    const rail = await screen.findByRole('navigation', { name: 'Admin sections' })
    expect(within(rail).getByRole('link', { name: 'Roles' })).toBeInTheDocument()
    expect(within(rail).queryByRole('link', { name: 'Users' })).not.toBeInTheDocument()
  })
})

describe('Add a user', () => {
  async function open(caps = [USERS, ROLES], routes: Record<string, unknown> = {}) {
    const calls = mockApi(caps, { 'GET /api/v1/admin/users/': page([ANN]), ...routes })
    renderAt('/admin/users')
    await screen.findByRole('link', { name: /Ann Ames/ })
    fireEvent.click(screen.getByRole('button', { name: 'Add user' }))
    return { calls, dialog: await screen.findByRole('dialog', { name: 'Add a user' }) }
  }

  it('is not offered to someone who cannot manage users', async () => {
    mockApi([ROLES, 'progress.view_results'], {})
    renderAt('/admin/users')
    expect(await screen.findByText('You don’t have access to this area')).toBeInTheDocument()
  })

  it('creates the user and shows a generated password once, with a copy button', async () => {
    const { calls, dialog } = await open(undefined, {
      'POST /api/v1/admin/users/': {
        status: 201,
        body: { ...DETAIL, id: 99, name: 'New Hire', email: 'new@example.com', temporary_password: 'Zx9-temp-pass' },
      },
    })
    fireEvent.change(within(dialog).getByLabelText('Email'), { target: { value: 'new@example.com' } })
    fireEvent.change(within(dialog).getByLabelText('Role'), { target: { value: 'trainer' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add user' }))

    expect(await screen.findByText('Zx9-temp-pass')).toBeInTheDocument()
    expect(screen.getByText(/shown once/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open New Hire' })).toHaveAttribute('href', '/admin/users/99')
    expect(bodyOf(calls, 'POST', '/admin/users/')[0]).toBeDefined()
  })

  it('sends the chosen role, and no role at all when the person cannot assign roles', async () => {
    const created = { status: 201, body: { ...DETAIL, id: 99, name: 'N', email: 'n@example.com' } }
    let sent: unknown
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit = {}) => {
        if (url.includes('/auth/session/'))
          return { ok: true, status: 200, statusText: 'x', json: async () => ({ authenticated: true, user: { id: 1, username: 'u', email: 'u@x.io', employee_id: null, must_change_password: false, roles: [], capabilities: [USERS] } }) }
        if ((init.method ?? 'GET') === 'POST') {
          sent = JSON.parse(String(init.body))
          return { ok: true, status: 201, statusText: 'x', json: async () => created.body }
        }
        return { ok: true, status: 200, statusText: 'x', json: async () => page([ANN]) }
      }),
    )
    renderAt('/admin/users')
    await screen.findByRole('link', { name: /Ann Ames/ })
    fireEvent.click(screen.getByRole('button', { name: 'Add user' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a user' })
    expect(within(dialog).queryByLabelText('Role')).not.toBeInTheDocument()
    fireEvent.change(within(dialog).getByLabelText('Email'), { target: { value: 'n@example.com' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add user' }))
    await screen.findByText('User added')
    expect(sent).toMatchObject({ email: 'n@example.com' })
    expect(sent).not.toHaveProperty('roles')
  })

  it('does not show a password that was typed', async () => {
    const { dialog } = await open(undefined, {
      'POST /api/v1/admin/users/': { status: 201, body: { ...DETAIL, id: 99, name: 'N', email: 'n@example.com' } },
    })
    fireEvent.change(within(dialog).getByLabelText('Email'), { target: { value: 'n@example.com' } })
    fireEvent.change(within(dialog).getByLabelText(/Password/), { target: { value: 'A-long-unusual-phrase-42' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add user' }))
    expect(await screen.findByText(/should change the password you set/)).toBeInTheDocument()
    expect(screen.queryByText('A-long-unusual-phrase-42')).not.toBeInTheDocument()
  })

  it('keeps the form and says why when the server refuses', async () => {
    const { dialog } = await open(undefined, {
      'POST /api/v1/admin/users/': { status: 400, body: { detail: 'Someone already has that email address.' } },
    })
    fireEvent.change(within(dialog).getByLabelText('Email'), { target: { value: 'ann@example.com' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add user' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Someone already has that email')
    expect(within(dialog).getByLabelText('Email')).toHaveValue('ann@example.com')
  })

  it('needs an email before it can be submitted', async () => {
    const { dialog } = await open()
    expect(within(dialog).getByRole('button', { name: 'Add user' })).toBeDisabled()
  })
})

describe('User detail', () => {
  const base = (extra: Record<string, unknown> = {}) => ({
    'GET /api/v1/admin/users/11/': { body: DETAIL },
    ...extra,
  })

  it('shows the profile, access and sign-in facts', async () => {
    mockApi([USERS, ROLES], base())
    renderAt('/admin/users/11')
    expect(await screen.findByRole('heading', { name: 'Ann Ames' })).toBeInTheDocument()
    expect(screen.getByLabelText('First name')).toHaveValue('Ann')
    expect(screen.getByLabelText('Employee id')).toHaveValue('E1')
    expect(screen.getByText('ann')).toBeInTheDocument() // username
    expect(screen.getByText('local · ann')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Results' })).toHaveAttribute(
      'href',
      '/admin/results/learners/11',
    )
  })

  it('saves only what changed, and only once something has', async () => {
    const calls = mockApi(
      [USERS],
      base({ 'PATCH /api/v1/admin/users/11/': { body: { ...DETAIL, first_name: 'Anna' } } }),
    )
    renderAt('/admin/users/11')
    const save = await screen.findByRole('button', { name: 'Save profile' })
    expect(save).toBeDisabled()
    fireEvent.change(screen.getByLabelText('First name'), { target: { value: 'Anna' } })
    expect(save).toBeEnabled()
    fireEvent.click(save)
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    const sent = JSON.parse(String(await lastBody(calls, 'PATCH')))
    expect(sent.first_name).toBe('Anna')
  })

  it('shows the server’s reason when a save is refused', async () => {
    mockApi(
      [USERS],
      base({
        'PATCH /api/v1/admin/users/11/': { status: 400, body: { detail: 'Someone already has that email address.' } },
      }),
    )
    renderAt('/admin/users/11')
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'bob@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Someone already has that email')
  })

  it('assigns roles — only for someone who may', async () => {
    mockApi([USERS], base())
    renderAt('/admin/users/11')
    await screen.findByRole('heading', { name: 'Ann Ames' })
    expect(screen.queryByRole('heading', { name: 'Roles' })).not.toBeInTheDocument()
  })

  it('saves a new set of roles', async () => {
    const calls = mockApi(
      [USERS, ROLES],
      base({ 'PUT /api/v1/admin/users/11/roles/': { body: { roles: ['learner', 'mentor'] } } }),
    )
    renderAt('/admin/users/11')
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Mentor' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save roles' }))
    expect(await screen.findByText('Roles saved.')).toBeInTheDocument()
    expect(JSON.parse(String(await lastBody(calls, 'PUT'))).roles.sort()).toEqual(['learner', 'mentor'])
  })

  it('says why a role change was refused', async () => {
    mockApi([USERS, ROLES], {
      'GET /api/v1/admin/users/11/': { body: { ...DETAIL, roles: ['admin'], is_self: true } },
      'PUT /api/v1/admin/users/11/roles/': { status: 400, body: { detail: 'You can’t remove your own Admin role.' } },
    })
    renderAt('/admin/users/11')
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Admin' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save roles' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('own Admin role')
  })

  it('asks before deactivating, then does it, and keeps saying so after the page refreshes', async () => {
    let active = true
    const calls = mockApi([USERS], {
      'GET /api/v1/admin/users/11/': () => ({ body: { ...DETAIL, is_active: active } }),
      'PATCH /api/v1/admin/users/11/': () => {
        active = false
        return { body: { ...DETAIL, is_active: false } }
      },
    })
    renderAt('/admin/users/11')
    fireEvent.click(await screen.findByRole('button', { name: 'Deactivate' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('Their progress and scores are kept')
    expect(bodyOf(calls, 'PATCH', '/users/11/')).toHaveLength(0)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Deactivate' }))
    // The page reloads the user as deactivated; the confirmation must survive that.
    expect(await screen.findByRole('button', { name: 'Reactivate' })).toBeInTheDocument()
    expect(screen.getByText('Deactivated.')).toBeInTheDocument()
    expect(JSON.parse(String(await lastBody(calls, 'PATCH')))).toEqual({ is_active: false })
  })

  it('does not let you deactivate yourself', async () => {
    mockApi([USERS], base({ 'GET /api/v1/admin/users/11/': { body: { ...DETAIL, is_self: true } } }))
    renderAt('/admin/users/11')
    expect(await screen.findByRole('button', { name: 'Deactivate' })).toBeDisabled()
  })

  it('offers to reactivate someone who is deactivated', async () => {
    mockApi([USERS], base({ 'GET /api/v1/admin/users/11/': { body: { ...DETAIL, is_active: false } } }))
    renderAt('/admin/users/11')
    expect(await screen.findByRole('button', { name: 'Reactivate' })).toBeEnabled()
    expect(screen.getByText('They can’t sign in. Their history is kept.')).toBeInTheDocument()
  })

  it('unlocks a locked account, and only shows the control when locked', async () => {
    const calls = mockApi(
      [USERS],
      base({
        'GET /api/v1/admin/users/11/': { body: { ...DETAIL, locked: true } },
        'POST /api/v1/admin/users/11/unlock/': { body: { cleared: 2 } },
      }),
    )
    renderAt('/admin/users/11')
    fireEvent.click(await screen.findByRole('button', { name: 'Unlock now' }))
    expect(await screen.findByText('Unlocked.')).toBeInTheDocument()
    expect(bodyOf(calls, 'POST', '/unlock/')).toHaveLength(1)
  })

  it('has no unlock control for an account that is not locked', async () => {
    mockApi([USERS], base())
    renderAt('/admin/users/11')
    await screen.findByRole('heading', { name: 'Ann Ames' })
    expect(screen.queryByRole('button', { name: 'Unlock now' })).not.toBeInTheDocument()
  })

  it('forces a password change', async () => {
    const calls = mockApi(
      [USERS],
      base({ 'PATCH /api/v1/admin/users/11/': { body: { ...DETAIL, must_change_password: true } } }),
    )
    renderAt('/admin/users/11')
    fireEvent.click(await screen.findByRole('button', { name: 'Require a change' }))
    expect(await screen.findByText('Marked to change their password at next sign-in.')).toBeInTheDocument()
    expect(JSON.parse(String(await lastBody(calls, 'PATCH')))).toEqual({ must_change_password: true })
  })

  it('generates a new password and shows it once', async () => {
    mockApi(
      [USERS],
      base({ 'POST /api/v1/admin/users/11/set-password/': { body: { temporary_password: 'Gen-1234-abc' } } }),
    )
    renderAt('/admin/users/11')
    fireEvent.click(await screen.findByRole('button', { name: 'Set password' }))
    const dialog = await screen.findByRole('dialog', { name: 'Set a new password' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Generate password' }))
    expect(await screen.findByText('Gen-1234-abc')).toBeInTheDocument()
    expect(screen.getByText(/signed out everywhere/)).toBeInTheDocument()
  })

  it('sets a typed password without echoing it, and explains a rejection', async () => {
    let attempts = 0
    mockApi([USERS], {
      ...base(),
      'POST /api/v1/admin/users/11/set-password/': () => {
        attempts += 1
        return attempts === 1
          ? { status: 400, body: { detail: 'This password is too short.' } }
          : { body: { ok: true } }
      },
    })
    renderAt('/admin/users/11')
    fireEvent.click(await screen.findByRole('button', { name: 'Set password' }))
    const dialog = await screen.findByRole('dialog', { name: 'Set a new password' })
    fireEvent.change(within(dialog).getByLabelText(/New password/), { target: { value: 'short' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Set password' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('too short')
    fireEvent.change(within(dialog).getByLabelText(/New password/), { target: { value: 'Another-long-phrase-77' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Set password' }))
    expect(await screen.findByText(/signed out everywhere/)).toBeInTheDocument()
    expect(screen.queryByText('Another-long-phrase-77')).not.toBeInTheDocument()
  })

  it('shows emergency access read-only to anyone but a superuser', async () => {
    mockApi([USERS], base())
    renderAt('/admin/users/11')
    expect(await screen.findByRole('checkbox', { name: 'Superuser' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Save access' })).not.toBeInTheDocument()
  })

  it('lets a superuser change it', async () => {
    const calls = mockApi(
      [USERS],
      base({
        'GET /api/v1/admin/users/11/': { body: { ...DETAIL, can_edit_privileges: true } },
        'PATCH /api/v1/admin/users/11/': { body: { ...DETAIL, is_staff: true } },
      }),
    )
    renderAt('/admin/users/11')
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Staff' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save access' }))
    expect(await screen.findByText('Access saved.')).toBeInTheDocument()
    expect(JSON.parse(String(await lastBody(calls, 'PATCH')))).toEqual({ is_staff: true, is_superuser: false })
  })

  it('handles an unknown user', async () => {
    mockApi([USERS], {})
    renderAt('/admin/users/99')
    expect(await screen.findByText('User not found')).toBeInTheDocument()
  })
})

describe('Roles', () => {
  const ACTIONS = [
    { key: 'catalog.author_content', label: 'Author courses', description: 'Create and edit courses in Studio.' },
    { key: 'accounts.manage_users', label: 'Manage users', description: 'Create and edit users.' },
    { key: 'accounts.manage_roles', label: 'Manage roles', description: 'Change what each role may do.' },
  ]
  const ROLE_ROWS = [
    { id: 1, name: 'learner', label: 'Learner', builtin: true, permissions: [], members: 4, locked: [] },
    { id: 2, name: 'trainer', label: 'Trainer', builtin: true, permissions: ['catalog.author_content'], members: 1, locked: [] },
    {
      id: 4,
      name: 'admin',
      label: 'Admin',
      builtin: true,
      permissions: ['catalog.author_content', 'accounts.manage_users', 'accounts.manage_roles'],
      members: 2,
      locked: ['accounts.manage_users', 'accounts.manage_roles'],
    },
  ]
  const matrix = { 'GET /api/v1/admin/roles/': { roles: ROLE_ROWS, actions: ACTIONS } }

  it('lays out every role against every action, in plain words', async () => {
    mockApi([ROLES], matrix)
    renderAt('/admin/roles')
    expect(await screen.findByText('Author courses')).toBeInTheDocument()
    expect(screen.getByText('Create and edit courses in Studio.')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Trainer can author courses' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Learner can author courses' })).not.toBeChecked()
    expect(screen.getByRole('link', { name: '4 people' })).toHaveAttribute('href', '/admin/users?role=learner')
    expect(screen.getByRole('link', { name: '1 person' })).toBeInTheDocument()
  })

  it('locks the things an Admin must always keep', async () => {
    mockApi([ROLES], matrix)
    renderAt('/admin/roles')
    const locked = await screen.findByRole('checkbox', { name: 'Admin can manage roles' })
    expect(locked).toBeChecked()
    expect(locked).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: 'Admin can author courses' })).toBeEnabled()
  })

  it('saves a tick straight away with the whole new set, and says what changed', async () => {
    const calls = mockApi([ROLES], {
      ...matrix,
      'PUT /api/v1/admin/roles/2/permissions/': {
        body: { ...ROLE_ROWS[1], permissions: ['catalog.author_content', 'accounts.manage_users'] },
      },
    })
    renderAt('/admin/roles')
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Trainer can manage users' }))
    expect(await screen.findByText('Trainer can now manage users.')).toBeInTheDocument()
    expect(JSON.parse(String(await lastBody(calls, 'PUT'))).permissions.sort()).toEqual([
      'accounts.manage_users',
      'catalog.author_content',
    ])
    expect(screen.getByRole('checkbox', { name: 'Trainer can manage users' })).toBeChecked()
  })

  it('leaves the grid as it was and says why when the server refuses', async () => {
    mockApi([ROLES], {
      ...matrix,
      'PUT /api/v1/admin/roles/2/permissions/': { status: 400, body: { detail: 'Permission x isn’t set up on this server.' } },
    })
    renderAt('/admin/roles')
    const box = await screen.findByRole('checkbox', { name: 'Trainer can manage users' })
    fireEvent.click(box)
    expect(await screen.findByRole('alert')).toHaveTextContent('isn’t set up')
    await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Trainer can manage users' })).not.toBeChecked())
  })

  it('is closed to anyone who cannot manage roles', async () => {
    mockApi([USERS], matrix)
    renderAt('/admin/roles')
    expect(await screen.findByText('You don’t have access to this area')).toBeInTheDocument()
  })
})

describe('Custom roles', () => {
  const ACTIONS = [
    { key: 'progress.view_results', label: 'View learner results', description: 'See scores.' },
    { key: 'audit.view_audit', label: 'View the audit log', description: 'See changes.' },
  ]
  const BUILTIN = { id: 1, name: 'learner', label: 'Learner', builtin: true, permissions: [], members: 4, locked: [] }
  const CUSTOM = {
    id: 9,
    name: 'senior_support',
    label: 'Senior support',
    builtin: false,
    permissions: ['progress.view_results'],
    members: 2,
    locked: [],
  }
  const withCustom = (extra: Record<string, unknown> = {}) => ({
    'GET /api/v1/admin/roles/': { roles: [BUILTIN, CUSTOM], actions: ACTIONS },
    ...extra,
  })

  it('offers the roles that exist, built in or added, in every picker', async () => {
    const options = {
      results: [
        { name: 'learner', label: 'Learner', builtin: true },
        { name: 'senior_support', label: 'Senior support', builtin: false },
      ],
    }
    mockApi([USERS, ROLES], {
      'GET /api/v1/admin/roles/options/': options,
      'GET /api/v1/admin/users/': page([{ ...ANN, roles: ['senior_support'] }]),
      'GET /api/v1/admin/users/11/': { body: { ...DETAIL, roles: ['senior_support'] } },
    })
    renderAt('/admin/users')
    const row = (await screen.findByRole('link', { name: /Ann Ames/ })).closest('tr')!
    expect(row).toHaveTextContent('Senior support') // the label, not the key
    expect(within(screen.getByLabelText('Role')).getByRole('option', { name: 'Senior support' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Add user' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a user' })
    expect(within(dialog).getByRole('option', { name: 'Senior support' })).toBeInTheDocument()
  })

  it('shows added roles as checkboxes on a user', async () => {
    mockApi([USERS, ROLES], {
      'GET /api/v1/admin/roles/options/': {
        results: [
          { name: 'learner', label: 'Learner', builtin: true },
          { name: 'senior_support', label: 'Senior support', builtin: false },
        ],
      },
      'GET /api/v1/admin/users/11/': { body: DETAIL },
    })
    renderAt('/admin/users/11')
    expect(await screen.findByRole('checkbox', { name: 'Senior support' })).not.toBeChecked()
  })

  it('adds a role, with the abilities ticked in the same step', async () => {
    const calls = mockApi([ROLES], {
      ...withCustom(),
      'POST /api/v1/admin/roles/new/': { status: 201, body: { ...CUSTOM, id: 10, name: 'auditor', label: 'Auditor' } },
    })
    renderAt('/admin/roles')
    fireEvent.click(await screen.findByRole('button', { name: 'Add role' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a role' })
    const submit = within(dialog).getByRole('button', { name: 'Add role' })
    expect(submit).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText('Role name'), { target: { value: 'Auditor' } })
    fireEvent.click(within(dialog).getByRole('checkbox', { name: /View the audit log/ }))
    fireEvent.click(submit)

    expect(await screen.findByText('Added the Auditor role.')).toBeInTheDocument()
    expect(JSON.parse(String(await lastBody(calls, 'POST')))).toEqual({
      name: 'Auditor',
      permissions: ['audit.view_audit'],
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('keeps the dialog open and says why when a role cannot be added', async () => {
    mockApi([ROLES], {
      ...withCustom(),
      'POST /api/v1/admin/roles/new/': { status: 400, body: { detail: 'There is already a role with that name.' } },
    })
    renderAt('/admin/roles')
    fireEvent.click(await screen.findByRole('button', { name: 'Add role' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a role' })
    fireEvent.change(within(dialog).getByLabelText('Role name'), { target: { value: 'Senior support' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add role' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('already a role')
    expect(within(dialog).getByLabelText('Role name')).toHaveValue('Senior support')
  })

  it('lists added roles, but not the built-in ones, for renaming and deleting', async () => {
    mockApi([ROLES], withCustom())
    renderAt('/admin/roles')
    const section = (await screen.findByRole('heading', { name: 'Roles you added' })).closest('section')!
    expect(within(section).getByText('Senior support')).toBeInTheDocument()
    expect(within(section).getByRole('link', { name: '2 people' })).toHaveAttribute(
      'href',
      '/admin/users?role=senior_support',
    )
    expect(within(section).queryByText('Learner')).not.toBeInTheDocument()
  })

  it('has no such section when only built-in roles exist', async () => {
    mockApi([ROLES], { 'GET /api/v1/admin/roles/': { roles: [BUILTIN], actions: ACTIONS } })
    renderAt('/admin/roles')
    await screen.findByText('View learner results')
    expect(screen.queryByRole('heading', { name: 'Roles you added' })).not.toBeInTheDocument()
  })

  it('renames a role', async () => {
    const calls = mockApi([ROLES], {
      ...withCustom(),
      'PATCH /api/v1/admin/roles/9/': { body: { ...CUSTOM, label: 'Tier 2' } },
    })
    renderAt('/admin/roles')
    fireEvent.click(await screen.findByRole('button', { name: 'Rename' }))
    const dialog = await screen.findByRole('dialog', { name: 'Rename role' })
    const save = within(dialog).getByRole('button', { name: 'Rename' })
    expect(save).toBeDisabled() // unchanged
    fireEvent.change(within(dialog).getByLabelText('Role name'), { target: { value: 'Tier 2' } })
    fireEvent.click(save)
    expect(await screen.findByText('Renamed.')).toBeInTheDocument()
    expect(JSON.parse(String(await lastBody(calls, 'PATCH')))).toEqual({ name: 'Tier 2' })
  })

  it('asks before deleting, then deletes', async () => {
    const calls = mockApi([ROLES], {
      ...withCustom(),
      'DELETE /api/v1/admin/roles/9/': { status: 204 },
    })
    renderAt('/admin/roles')
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('recorded in the audit log')
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete role' }))
    expect(await screen.findByText('Deleted the Senior support role.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true)
  })

  it('says why a role in use cannot be deleted', async () => {
    mockApi([ROLES], {
      ...withCustom(),
      'DELETE /api/v1/admin/roles/9/': {
        status: 409,
        body: { detail: '2 people hold this role. Move them to another role first.' },
      },
    })
    renderAt('/admin/roles')
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete role' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Move them to another role first')
  })
})

/** The JSON body of the most recent call with `method`. */
async function lastBody(calls: Call[], method: string): Promise<unknown> {
  const fetchMock = globalThis.fetch as unknown as { mock: { calls: [string, RequestInit][] } }
  const matches = fetchMock.mock.calls.filter(([, init]) => (init?.method ?? 'GET').toUpperCase() === method)
  expect(calls.length).toBeGreaterThan(0)
  return matches[matches.length - 1][1].body
}
