import { useState } from 'react'

import { DataTable, type Column } from '../../components/DataTable'
import { PageState } from '../../components/PageState'
import { useCan } from '../../lib/capabilities'
import { CAN } from '../../lib/capabilityKeys'
import { AdminPage, Toolbar } from './AdminPage'
import { adminApi, type CaseRow, type CaseStatus, type RatingRow } from './adminApi'
import { formatDateTime, hoursText, untilText } from './format'
import { useQuery } from './useQuery'
import styles from './ratings.module.css'

type Tab = 'mine' | 'pool' | 'all' | 'cases'

const CASE_STATUS: Record<CaseStatus, string> = {
  not_submitted: 'Not handed in',
  waiting: 'Waiting for a mentor',
  changes_requested: 'Changes requested',
  passed: 'Passed',
  waived: 'Waived',
  not_passed: 'Closed, not passed',
}

/** The review queue: work waiting for a mentor, and (for trainers and admins) the cases that
 * need someone to step in. */
export function RatingsPage() {
  const canRate = useCan(CAN.rateSimulations)
  const canManage = useCan(CAN.manageReviews)
  const [tab, setTab] = useState<Tab>(canRate ? 'mine' : 'all')
  const [overdue, setOverdue] = useState(false)
  const [attention, setAttention] = useState(false)
  const [page, setPage] = useState(1)

  const query = {
    tab,
    page,
    ...(overdue ? { overdue: '1' } : {}),
    ...(attention ? { attention: '1' } : {}),
  }
  const list = useQuery(() => adminApi.ratingsQueue<RatingRow & CaseRow>(query), JSON.stringify(query))
  const stats = useQuery(() => (canManage ? adminApi.ratingStats() : Promise.resolve(null)), `stats-${canManage}`)
  const counts = list.data?.counts ?? {}

  const tabs: { key: Tab; label: string; show: boolean }[] = [
    { key: 'mine', label: `Mine${counts.mine !== undefined ? ` (${counts.mine})` : ''}`, show: canRate },
    { key: 'pool', label: `Shared pool${counts.pool !== undefined ? ` (${counts.pool})` : ''}`, show: canRate },
    { key: 'all', label: `All waiting${counts.all !== undefined ? ` (${counts.all})` : ''}`, show: canManage },
    { key: 'cases', label: 'Needs a trainer', show: canManage },
  ]

  const submissionColumns: Column<RatingRow>[] = [
    {
      key: 'learner',
      header: 'Learner',
      render: (r) => (
        <>
          {r.learner.name}
          <span className={styles.sub}>{r.learner.email}</span>
        </>
      ),
    },
    {
      key: 'activity',
      header: 'Simulation',
      render: (r) => (
        <>
          {r.activity.title}
          <span className={styles.sub}>{r.course}</span>
        </>
      ),
    },
    {
      key: 'revision',
      header: 'Revision',
      hideOnMobile: true,
      render: (r) => (
        <>
          {r.revision}
          {r.late && <span className={styles.sub}>handed in late</span>}
        </>
      ),
    },
    { key: 'submitted', header: 'Handed in', hideOnMobile: true, render: (r) => formatDateTime(r.submitted_at) },
    {
      key: 'due',
      header: 'Review due',
      render: (r) => {
        const due = untilText(r.review_due_at)
        return <span className={due.overdue ? styles.overdue : undefined}>{due.text}</span>
      },
    },
    {
      key: 'route',
      header: 'With',
      hideOnMobile: true,
      render: (r) => {
        const by = r.claimed_by_me ? 'you' : r.claimed_by
        if (r.own) {
          return (
            <>
              Your own work
              <span className={styles.sub}>someone else must rate it</span>
            </>
          )
        }
        const where =
          r.route === 'mine'
            ? 'You'
            : r.route === 'escalated'
              ? `Open to any mentor (was ${r.assigned_mentor ?? 'unassigned'})`
              : r.route === 'routed'
                ? (r.assigned_mentor ?? 'A mentor')
                : 'Shared pool'
        return (
          <>
            {where}
            {by && <span className={styles.sub}>being rated by {by}</span>}
            {r.needs_attention && <span className={styles.sub}>needs attention — several reviews asked for changes</span>}
          </>
        )
      },
    },
  ]

  const caseColumns: Column<CaseRow>[] = [
    {
      key: 'learner',
      header: 'Learner',
      render: (r) => (
        <>
          {r.learner.name}
          <span className={styles.sub}>{r.learner.email}</span>
        </>
      ),
    },
    {
      key: 'activity',
      header: 'Simulation',
      render: (r) => (
        <>
          {r.activity.title}
          <span className={styles.sub}>{r.course}</span>
        </>
      ),
    },
    { key: 'status', header: 'Where it stands', render: (r) => CASE_STATUS[r.status] },
    {
      key: 'due',
      header: 'Deadline',
      render: (r) =>
        r.due_at ? (
          <span className={r.overdue ? styles.overdue : undefined}>
            {r.overdue ? 'Overdue — ' : ''}
            {formatDateTime(r.due_at)}
          </span>
        ) : (
          '—'
        ),
    },
    {
      key: 'revisions',
      header: 'Revisions',
      hideOnMobile: true,
      render: (r) => (
        <>
          {r.revisions}
          {r.needs_attention && <span className={styles.sub}>{r.unsuccessful} reviews asked for changes</span>}
        </>
      ),
    },
  ]

  const onCases = tab === 'cases'
  const median = stats.data?.median_hours
  return (
    <AdminPage
      eyebrow="Review"
      title="Ratings"
      hint="Mentor-rated simulations waiting for a review. Work routed to a learner’s mentor shows under Mine; everything else is in the shared pool for any mentor to take."
    >
      <div role="tablist" aria-label="Review queues" className={styles.tabs}>
        {tabs
          .filter((t) => t.show)
          .map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              className={styles.tab}
              onClick={() => {
                setTab(t.key)
                setPage(1)
              }}
            >
              {t.label}
            </button>
          ))}
      </div>

      {stats.data && (
        <p className={styles.stats} role="status">
          {median != null ? `Reviews took a median of ${hoursText(median)} over the last ${stats.data.window_days} days. ` : 'No reviews yet in the last 30 days. '}
          {stats.data.waiting} waiting · {stats.data.waiting_overdue} overdue · {stats.data.escalated} open to any mentor.
        </p>
      )}

      <Toolbar>
        {!onCases && (
          <label>
            <input
              type="checkbox"
              checked={overdue}
              onChange={(e) => {
                setOverdue(e.target.checked)
                setPage(1)
              }}
            />{' '}
            Review overdue
          </label>
        )}
        <label>
          <input
            type="checkbox"
            checked={attention}
            onChange={(e) => {
              setAttention(e.target.checked)
              setPage(1)
            }}
          />{' '}
          Needs attention
        </label>
      </Toolbar>

      {list.loading ? (
        <PageState kind="loading" />
      ) : list.error || !list.data ? (
        <PageState kind="error" title="Couldn’t load the queue" onRetry={list.reload}>
          {list.error}
        </PageState>
      ) : (
        <>
          {onCases ? (
            <DataTable
              label="Cases that need a trainer"
              columns={caseColumns}
              rows={list.data.results as unknown as CaseRow[]}
              rowKey={(r) => r.case_id}
              rowHref={(r) => `/admin/results/learners/${r.learner.id}`}
              meta={list.data}
              busy={list.refreshing}
              onPage={setPage}
              empty="Nothing needs a trainer right now: no one is overdue and no case has had several reviews asking for changes."
            />
          ) : (
            <DataTable
              label="Simulations waiting for review"
              columns={submissionColumns}
              rows={list.data.results as unknown as RatingRow[]}
              rowKey={(r) => r.id}
              rowHref={(r) => `/admin/ratings/${r.id}`}
              meta={list.data}
              busy={list.refreshing}
              onPage={setPage}
              empty={
                tab === 'mine'
                  ? 'Nothing is assigned to you right now. Check the shared pool for work nobody has taken yet.'
                  : 'Nothing is waiting here.'
              }
            />
          )}
        </>
      )}
    </AdminPage>
  )
}
