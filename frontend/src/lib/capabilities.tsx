import type { ReactNode } from 'react'

import { useAuth } from './auth'

export function useCan(action: string): boolean {
  const { user } = useAuth()
  return !!user?.capabilities.includes(action)
}

/** True when the user holds at least one of `actions`. */
export function useCanAny(actions: readonly string[]): boolean {
  const { user } = useAuth()
  return !!user && actions.some((a) => user.capabilities.includes(a))
}

/** Renders `children` only for users who hold `action`; otherwise a quiet
 * "no access" message (a direct URL visit by a learner, say). */
export function RequireCapability({
  action,
  any,
  children,
}: {
  action?: string
  /** Allow anyone holding at least one of these. */
  any?: readonly string[]
  children: ReactNode
}) {
  const single = useCan(action ?? '')
  const some = useCanAny(any ?? [])
  const allowed = any ? some : single
  if (!allowed) {
    return (
      <div style={{ maxWidth: 560, margin: '0 auto', padding: '64px 24px' }}>
        <h1 style={{ fontSize: '1.375rem' }}>You don’t have access to this area</h1>
        <p style={{ marginTop: 8, color: 'var(--text-muted)' }}>
          If you think you should, ask an administrator to update your role.
        </p>
      </div>
    )
  }
  return <>{children}</>
}
