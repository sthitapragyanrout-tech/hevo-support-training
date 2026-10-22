import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, page, renderAt } from './testHelpers'

const USERS = 'accounts.manage_users'

afterEach(() => vi.unstubAllGlobals())

const OK = [
  {
    id: 1,
    when: '2026-10-23T10:00:00Z',
    username: 'ann',
    user_id: 11,
    name: 'Ann Ames',
    ip_address: '10.0.0.1',
    user_agent: 'Chrome on Mac',
    signed_out_at: null,
  },
  {
    id: 2,
    when: '2026-10-20T10:00:00Z',
    username: 'ghost',
    user_id: null,
    name: null,
    ip_address: '10.0.0.2',
    user_agent: 'Firefox',
    signed_out_at: '2026-10-20T11:00:00Z',
  },
]
const FAILED = [
  {
    id: 5,
    when: '2026-10-23T10:05:00Z',
    username: 'ann',
    user_id: 11,
    name: 'Ann Ames',
    ip_address: '10.0.0.9',
    user_agent: 'curl',
    locked_out: true,
  },
  { ...OK[1], id: 6, locked_out: false, signed_out_at: undefined },
]

const feed = (kind: 'success' | 'failed' = 'success') => ({
  'GET /api/v1/admin/signins/': (c: { query: URLSearchParams }) => ({
    body: {
      ...page<object>(c.query.get('kind') === 'failed' ? FAILED : OK),
      kind: c.query.get('kind') ?? kind,
    },
  }),
})

describe('Sign-in activity', () => {
  it('lists sign-ins with who, where and when they signed out', async () => {
    mockApi([USERS], feed())
    renderAt('/admin/signins')
    const ann = (await screen.findByRole('link', { name: 'Ann Ames' })).closest('tr')!
    expect(ann).toHaveTextContent('ann')
    expect(ann).toHaveTextContent('10.0.0.1')
    expect(ann).toHaveTextContent('Chrome on Mac')
    expect(screen.getByRole('link', { name: 'Ann Ames' })).toHaveAttribute('href', '/admin/users/11')
    const ghost = screen.getByText('ghost').closest('tr')!
    expect(ghost).toHaveTextContent('No such account')
    expect(within(ghost).queryByRole('link')).not.toBeInTheDocument()
  })

  it('switches to failed attempts, which say whether they locked the account', async () => {
    const calls = mockApi([USERS], feed())
    renderAt('/admin/signins')
    await screen.findByRole('link', { name: 'Ann Ames' })
    fireEvent.change(screen.getByLabelText('Show'), { target: { value: 'failed' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('kind') === 'failed')).toBe(true))
    expect(await screen.findByText('Locked the account')).toBeInTheDocument()
    expect(screen.getByText('Refused')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Result' })).toBeInTheDocument()
  })

  it('offers "only lockouts" for failures alone, and sends it', async () => {
    const calls = mockApi([USERS], feed())
    renderAt('/admin/signins')
    await screen.findByRole('link', { name: 'Ann Ames' })
    expect(screen.queryByLabelText('Only lockouts')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Show'), { target: { value: 'failed' } })
    fireEvent.click(await screen.findByLabelText('Only lockouts'))
    await waitFor(() => expect(calls.some((c) => c.query.get('locked') === 'true')).toBe(true))
  })

  it('searches and filters by date', async () => {
    const calls = mockApi([USERS], feed())
    renderAt('/admin/signins')
    await screen.findByRole('link', { name: 'Ann Ames' })
    fireEvent.change(screen.getByLabelText('Search sign-in activity'), { target: { value: '10.0.0.2' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('search') === '10.0.0.2')).toBe(true))
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-10-01' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('from') === '2026-10-01')).toBe(true))
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-10-31' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('to') === '2026-10-31')).toBe(true))
  })

  it('opens already searching for an account (the user page links here)', async () => {
    const calls = mockApi([USERS], feed())
    renderAt('/admin/signins?search=ann')
    await screen.findByRole('link', { name: 'Ann Ames' })
    expect(screen.getByLabelText('Search sign-in activity')).toHaveValue('ann')
    expect(calls.some((c) => c.query.get('search') === 'ann')).toBe(true)
  })

  it('is honest when there is nothing to show', async () => {
    mockApi([USERS], { 'GET /api/v1/admin/signins/': { body: { ...page([]), kind: 'success' } } })
    renderAt('/admin/signins')
    expect(await screen.findByText('No sign-ins recorded yet.')).toBeInTheDocument()
  })

  it('is closed to anyone who cannot manage users', async () => {
    mockApi(['progress.view_results'], feed())
    renderAt('/admin/signins')
    expect(await screen.findByText('You don’t have access to this area')).toBeInTheDocument()
  })

  it('is linked from the user page', async () => {
    mockApi([USERS], {
      'GET /api/v1/admin/users/11/': {
        body: {
          id: 11, name: 'Ann Ames', email: 'ann@example.com', username: 'ann', employee_id: null,
          is_active: true, roles: [], last_login: null, locked: false, must_change_password: false,
          first_name: 'Ann', last_name: 'Ames', timezone: 'Asia/Kolkata', date_joined: '2026-09-01T10:00:00Z',
          is_staff: false, is_superuser: false, can_edit_privileges: false, is_self: false, identities: [],
        },
      },
    })
    renderAt('/admin/users/11')
    expect(await screen.findByRole('link', { name: 'Sign-in activity' })).toHaveAttribute(
      'href',
      '/admin/signins?search=ann',
    )
  })
})
