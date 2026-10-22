import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

import { authApi, type User } from './api'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (login: string, password: string) => Promise<void>
  logout: () => Promise<void>
  /** Change the signed-in person's own password; updates who they are. */
  changePassword: (current: string, next: string) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    authApi
      .session()
      .then((res) => setUser(res.user))
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  async function login(loginValue: string, password: string) {
    const res = await authApi.login(loginValue, password)
    setUser(res.user)
  }

  async function logout() {
    await authApi.logout()
    setUser(null)
  }

  async function changePassword(current: string, next: string) {
    const res = await authApi.changePassword(current, next)
    setUser(res.user)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, changePassword }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
