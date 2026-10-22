import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderAt } from '../admin/testHelpers'

afterEach(() => vi.unstubAllGlobals())

const USER_AFTER = {
  id: 1,
  username: 'u',
  email: 'u@example.com',
  employee_id: null,
  must_change_password: false,
  password_change_required: false,
  roles: [],
  capabilities: [],
}

const fill = (current: string, next: string, again = next) => {
  fireEvent.change(screen.getByLabelText(/Current password|Temporary password/), { target: { value: current } })
  fireEvent.change(screen.getByLabelText(/^New password/), { target: { value: next } })
  fireEvent.change(screen.getByLabelText(/^Confirm new password/), { target: { value: again } })
}

describe('Change your password', () => {
  it('is reachable from the account menu', async () => {
    mockApi([], { 'GET /api/v1/catalog/courses/': [] })
    renderAt('/')
    fireEvent.click(await screen.findByRole('button', { name: 'Account menu' }))
    expect(await screen.findByRole('link', { name: 'Change password' })).toHaveAttribute(
      'href',
      '/account/password',
    )
  })

  it('changes it, sends exactly what was typed, and says so', async () => {
    const calls = mockApi([], {
      'POST /api/v1/auth/password/': { body: { user: USER_AFTER } },
    })
    renderAt('/account/password')
    expect(await screen.findByRole('heading', { name: 'Change your password' })).toBeInTheDocument()
    fill('old-password-1', 'A-brand-new-phrase-91')
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByText('Your password has been changed.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.path.endsWith('/auth/password/'))).toBe(true)
    const sent = JSON.parse(
      String((globalThis.fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls.find(
        ([u]) => u.endsWith('/auth/password/'),
      )?.[1].body),
    )
    expect(sent).toEqual({ current_password: 'old-password-1', new_password: 'A-brand-new-phrase-91' })
    // The form is cleared once it has been used.
    expect(screen.getByLabelText(/^New password/)).toHaveValue('')
  })

  it('will not submit until the two new passwords match', async () => {
    mockApi([], {})
    renderAt('/account/password')
    await screen.findByRole('heading', { name: 'Change your password' })
    fill('old', 'one-new-phrase-12', 'another-phrase-34')
    expect(screen.getByText('These don’t match yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change password' })).toBeDisabled()
  })

  it('needs every field', async () => {
    mockApi([], {})
    renderAt('/account/password')
    await screen.findByRole('heading', { name: 'Change your password' })
    expect(screen.getByRole('button', { name: 'Change password' })).toBeDisabled()
  })

  it('shows the server’s reason and keeps what you typed when it is refused', async () => {
    mockApi([], {
      'POST /api/v1/auth/password/': { status: 400, body: { detail: 'Your current password isn’t right.' } },
    })
    renderAt('/account/password')
    await screen.findByRole('heading', { name: 'Change your password' })
    fill('wrong', 'A-brand-new-phrase-91')
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('current password isn’t right')
    expect(screen.getByLabelText(/^New password/)).toHaveValue('A-brand-new-phrase-91')
  })
})

describe('A temporary password must be replaced first (when enforcement is on)', () => {
  const forced = { must_change_password: true, password_change_required: true }

  it('sends someone with a temporary password straight to the change screen, from anywhere', async () => {
    mockApi([], { 'GET /api/v1/catalog/courses/': [] }, forced)
    renderAt('/')
    expect(await screen.findByRole('heading', { name: 'Choose a new password' })).toBeInTheDocument()
    expect(screen.getByText(/signed in with a temporary password/)).toBeInTheDocument()
    expect(screen.getByLabelText('Temporary password')).toBeInTheDocument()
  })

  it('does the same for a deep link', async () => {
    mockApi(['catalog.author_content'], {}, forced)
    renderAt('/studio')
    expect(await screen.findByRole('heading', { name: 'Choose a new password' })).toBeInTheDocument()
  })

  it('leaves them nowhere else to go until they have', async () => {
    mockApi(['catalog.author_content', 'progress.view_results'], {}, forced)
    renderAt('/')
    await screen.findByRole('heading', { name: 'Choose a new password' })
    // Not merely hidden: the navigation isn't on the page at all.
    expect(document.querySelector('nav')).toBeNull()
    expect(screen.queryByRole('link', { name: 'Studio' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'My courses' })).not.toBeInTheDocument()
  })

  it('once changed, takes them on to the app', async () => {
    mockApi([], {
      'GET /api/v1/catalog/courses/': [],
      'POST /api/v1/auth/password/': { body: { user: USER_AFTER } },
    }, forced)
    renderAt('/')
    await screen.findByRole('heading', { name: 'Choose a new password' })
    fill('temp-pass-123', 'A-brand-new-phrase-91')
    fireEvent.click(screen.getByRole('button', { name: 'Set password and continue' }))
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Choose a new password' })).not.toBeInTheDocument())
    expect(await screen.findByRole('link', { name: 'My courses' })).toBeInTheDocument()
  })

  it('does nothing of the kind while enforcement is off, even for a flagged account', async () => {
    mockApi([], { 'GET /api/v1/catalog/courses/': [] }, { must_change_password: true, password_change_required: false })
    renderAt('/')
    expect(await screen.findByRole('link', { name: 'My courses' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Choose a new password' })).not.toBeInTheDocument()
  })

  it('does not trap someone who has already changed theirs', async () => {
    mockApi([], { 'GET /api/v1/catalog/courses/': [] })
    renderAt('/')
    expect(await screen.findByRole('link', { name: 'My courses' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Choose a new password' })).not.toBeInTheDocument()
  })
})
