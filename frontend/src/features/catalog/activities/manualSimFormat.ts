import type { RatedStatus, RatedSummary } from '../../../lib/api'

/** "Fri 31 Oct, 10:00" in the viewer's own time zone. */
export function when(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** "3.5 / 5" — a rating is never shown as a percentage. */
export const score = (n: number) => `${Number(n.toFixed(2))} / 5`

export interface StatusLine {
  /** One calm sentence for the row's second line. */
  line: string
  /** Something a person should act on (overdue, changes asked for). */
  attention: boolean
}

/** What to say about where the learner's work stands, from the server's small summary. */
export function statusLine(rated: RatedSummary | undefined, fallback: string): StatusLine {
  if (!rated) return { line: fallback, attention: false }
  const due = rated.due_at ? `by ${when(rated.due_at)}` : ''
  const lines: Record<RatedStatus, string> = {
    not_opened: fallback,
    not_submitted: rated.overdue
      ? `Overdue — was due ${when(rated.due_at)}. You can still hand it in.`
      : rated.due_at
        ? `Not handed in · due ${when(rated.due_at)}`
        : 'Not handed in yet',
    waiting: 'Handed in · waiting for your mentor',
    changes_requested: rated.overdue
      ? `Changes requested — revision was due ${when(rated.due_at)}`
      : `Changes requested${due ? ` — revise ${due}` : ''}`,
    passed: rated.last_score != null ? `Done · rated ${score(rated.last_score)}` : 'Done',
    waived: 'Excused by your trainer',
    not_passed: 'Closed by your trainer',
  }
  return {
    line: lines[rated.status],
    attention: rated.status === 'changes_requested' || (rated.overdue && rated.status !== 'waiting'),
  }
}
