import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from '../lib/auth'

export const PASSWORD_PATH = '/account/password'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <p>Loading…</p>
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  // A temporary or reset password must be replaced before anything else.
  if (user.password_change_required && location.pathname !== PASSWORD_PATH) {
    return <Navigate to={PASSWORD_PATH} replace />
  }
  return <>{children}</>
}
