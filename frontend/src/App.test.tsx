import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { mockApi, renderAt } from './features/admin/testHelpers'
import { AuthProvider } from './lib/auth'

afterEach(() => vi.unstubAllGlobals())

describe('App', () => {
  it('redirects an unauthenticated visitor to the login page', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    )
    // The session check (GET /api/v1/auth/session/) has nothing real to
    // hit in this test environment and resolves to "not authenticated" —
    // ProtectedRoute should redirect to /login rather than render the
    // dashboard.
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('says so, inside the app, when the address does not exist, and offers the way back', async () => {
    mockApi([], {})
    renderAt('/admin/not-a-real-page')
    expect(
      await screen.findByRole('heading', { name: 'We can’t find that page' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to My courses' })).toHaveAttribute('href', '/')
    // Still inside the shell: the header and navigation are there.
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument()
  })
})
