import type { ActivityStatus } from './adminApi'

export const percent = (score: number | null) =>
  score === null ? '—' : `${Math.round(score * 100)}%`

export function formatWhen(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return `${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} · ${d.toLocaleTimeString(
    undefined,
    { hour: '2-digit', minute: '2-digit' },
  )}`
}

/** Plain words for where a learner stands on an activity. */
export function statusLabel(state: ActivityStatus, type: string): string {
  if (state === 'completed') return type === 'reading' ? 'Read' : 'Passed'
  if (state === 'exhausted') return 'Not passed'
  if (state === 'started') return 'In progress'
  return 'Not started'
}

/** "results.reset_attempts" → "Reset attempts". */
export function actionLabel(action: string): string {
  const last = action.split('.').pop() ?? action
  const words = last.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** Plain-words state of an account. */
export function accountState(u: { is_active: boolean; locked: boolean }): string {
  if (!u.is_active) return 'Deactivated'
  if (u.locked) return 'Locked'
  return 'Active'
}
