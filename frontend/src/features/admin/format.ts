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
  if (state === 'completed') {
    return type === 'reading' ? 'Read' : type === 'video' ? 'Watched' : type === 'bot_sim' ? 'Completed' : 'Passed'
  }
  if (state === 'exhausted') return type === 'bot_sim' ? 'All tickets used' : type === 'manual_sim' ? 'Closed' : 'Not passed'
  if (state === 'started') return 'In progress'
  return 'Not started'
}

/** The kind of activity, in a word. */
export function typeLabel(type: string): string {
  if (type === 'bot_sim') return 'Practice ticket'
  if (type === 'manual_sim') return 'Mentor-rated simulation'
  return type === 'mcq' ? 'Quiz' : type === 'video' ? 'Video' : 'Reading'
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

/** "in 5 h", "in 2 d", or "overdue by 1 d" — for a deadline relative to now. */
export function untilText(iso: string, now: number = Date.now()): { text: string; overdue: boolean } {
  const minutes = Math.round((new Date(iso).getTime() - now) / 60000)
  const abs = Math.abs(minutes)
  const span = abs < 60 ? `${abs} min` : abs < 48 * 60 ? `${Math.round(abs / 60)} h` : `${Math.round(abs / 1440)} d`
  return minutes < 0 ? { text: `overdue by ${span}`, overdue: true } : { text: `in ${span}`, overdue: false }
}

/** Whole hours as "14 h", or "2.5 d" when long. */
export function hoursText(hours: number): string {
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`
  return hours >= 48 ? `${Number((hours / 24).toFixed(1))} d` : `${Number(hours.toFixed(1))} h`
}
