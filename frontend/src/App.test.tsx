import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import App from './App'
import { AuthProvider } from './lib/auth'

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
})
