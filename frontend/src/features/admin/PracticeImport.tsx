import { useEffect, useState } from 'react'

import { Dialog } from '../../components/Dialog'
import { ApiError } from '../../lib/api'
import { adminApi, type BankStatus, type PracticeOptions, type ScenarioImportRow } from './adminApi'
import { formatDateTime, formatWhen } from './format'
import { useQuery } from './useQuery'
import styles from './practice.module.css'

/** Plain-language reasons a past ticket (or its rewrite) wasn't used. */
const NOT_USED: Record<string, string> = {
  'zendesk:not_typed_by_customer': 'created by a rule, the system or the API — not typed by a customer',
  'zendesk:submitted_for_customer': 'opened by an agent on the customer’s behalf',
  'zendesk:author_not_requester': 'the first message wasn’t from the customer',
  'zendesk:first_comment_not_public': 'the first message was an internal note',
  'zendesk:requester_not_end_user': 'written by staff, not a customer',
  'zendesk:unknown_author': 'the author couldn’t be confirmed',
  'zendesk:staff_email': 'sent from a staff email address',
  'zendesk:excluded_requester': 'from an excluded account',
  'zendesk:excluded_group': 'from an excluded group',
  'zendesk:excluded_tag': 'carries an excluded tag',
  'zendesk:empty_message': 'no message text',
  'zendesk:no_comments': 'no messages',
  'zendesk:missing_fields': 'the ticket was missing details we need to trust it',
  'rewrite:not_usable': 'needs account access, or isn’t one question the docs can answer',
  'rewrite:pii_left': 'personal details couldn’t be removed from it',
  'rewrite:foreign_url': 'mentions a link that isn’t Hevo’s documentation',
  'rewrite:name_left': 'a name was left in it',
  'rewrite:length': 'too short or too long',
  'rewrite:no_hints': 'no documentation keywords',
  'rewrite:not_english': 'not in English',
  'rewrite:low_confidence': 'the model wasn’t confident enough',
  'rewrite:other_topic': 'a different topic from the one chosen',
}

const labelFor = (reason: string) => NOT_USED[reason] ?? reason

const active = (r: ScenarioImportRow) => r.state === 'queued' || r.state === 'running'

function summary(r: ScenarioImportRow): string {
  const parts = [`${r.approved} approved automatically`, `${r.drafted} for a trainer to review`]
  if (r.duplicates) parts.push(`${r.duplicates} duplicates left out`)
  if (r.failed) parts.push(`${r.failed} failed`)
  return parts.join(' · ')
}

interface PanelProps {
  options: PracticeOptions
  /** Administrators only: start imports, send a batch back, switch automatic approval. */
  canAdmin: boolean
  onImported: (message: string) => void
  /** Show just the scenarios from this run. */
  onShowRun: (id: number) => void
  /** Show the drafts waiting for review. */
  onReviewDrafts: () => void
  onChanged: () => void
}

/** Tells whoever looks after the practice questions when learners can't get one (or are
 * running short), and what to do about it. Quiet when the bank is healthy. */
function BankBanner({
  bank,
  blocked,
  canAdmin,
  onReviewDrafts,
  onImport,
}: {
  bank: BankStatus
  blocked: string | null
  canAdmin: boolean
  onReviewDrafts: () => void
  onImport: () => void
}) {
  if (bank.state === 'ok') return null
  const canImport = canAdmin && blocked === null
  if (bank.state === 'low') {
    return (
      <p role="status" className={styles.bankLow}>
        <strong>Only {bank.approved} approved {bank.approved === 1 ? 'question' : 'questions'}</strong> (we aim for{' '}
        {bank.target}). Learners can still practise, but they will see repeats sooner.
      </p>
    )
  }
  return (
    <section role="alert" className={styles.bankEmpty} aria-label="No practice questions">
      <p>
        <strong>No approved practice scenarios — learners can’t start practice.</strong>
      </p>
      <p className={styles.hint}>
        {bank.drafts > 0
          ? `${bank.drafts} ${bank.drafts === 1 ? 'draft is' : 'drafts are'} waiting for review. Approve some and learners can start straight away.`
          : canImport
            ? 'Import some from past customer queries, or write one yourself.'
            : 'Write one yourself with New scenario, or generate drafts.'}
        {!canImport && blocked && bank.drafts === 0 && ` Importing is off — ${blocked}`}
        {!canAdmin && ' Only an administrator can import.'}
      </p>
      <p className={styles.runActions}>
        {bank.drafts > 0 && (
          <button type="button" className="btn btn-primary btn-sm" onClick={onReviewDrafts}>
            Review drafts
          </button>
        )}
        {canImport && (
          <button type="button" className="btn btn-sm" onClick={onImport}>
            Import now
          </button>
        )}
      </p>
    </section>
  )
}

/** Where practice questions can come from real past customer queries — read-only —
 * and the controls for reviewing what came in. */
export function ZendeskPanel({ options, canAdmin, onImported, onShowRun, onReviewDrafts, onChanged }: PanelProps) {
  const z = options.zendesk
  const runs = useQuery(() => adminApi.imports(), 'imports')
  const [dialog, setDialog] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState<ScenarioImportRow | null>(null)

  const rows = runs.data?.results ?? []
  const running = rows.some(active)
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => {
      runs.reload()
      onChanged()
    }, 3000)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running])

  async function flip(on: boolean) {
    setBusy(true)
    setProblem(null)
    try {
      await adminApi.setAutoApprove(on)
      onChanged()
    } catch (err) {
      setProblem(err instanceof ApiError && err.message ? err.message : 'That didn’t save. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function flipTopUp(on: boolean) {
    setBusy(true)
    setProblem(null)
    try {
      await adminApi.setTopUp(on)
      onChanged()
    } catch (err) {
      setProblem(err instanceof ApiError && err.message ? err.message : 'That didn’t save. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function revert(run: ScenarioImportRow) {
    setConfirming(null)
    setBusy(true)
    setProblem(null)
    try {
      const done = await adminApi.revertImport(run.id)
      onImported(`Sent ${done.sent_back} ${done.sent_back === 1 ? 'question' : 'questions'} from import #${run.id} back to draft.`)
      runs.reload()
      onChanged()
    } catch (err) {
      setProblem(err instanceof ApiError && err.message ? err.message : 'That didn’t work. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const blocked = z.blocked_reason
  const top = options.topup
  return (
    <>
    <BankBanner
      bank={options.bank}
      blocked={blocked}
      canAdmin={canAdmin}
      onReviewDrafts={onReviewDrafts}
      onImport={() => setDialog(true)}
    />
    <section className={styles.panel} aria-label="Past customer queries">
      <div className={styles.panelHead}>
        <div>
          <h2 className={styles.panelTitle}>Past customer queries</h2>
          <p className={styles.hint}>
            Practice questions can be written from real, closed Zendesk tickets. We only read — nothing is ever sent
            to or changed in Zendesk. Only messages a customer wrote themselves are used; each is rewritten without
            personal details, and only the rewrite is kept.
          </p>
        </div>
        <button
          type="button"
          className="btn"
          disabled={!canAdmin || blocked !== null}
          onClick={() => setDialog(true)}
          title={!canAdmin ? 'Only an administrator can import' : (blocked ?? undefined)}
        >
          Import from Zendesk
        </button>
      </div>

      <p className={styles.statusLine} role="status">
        <strong>Zendesk:</strong> {z.configured ? 'connected' : 'not connected'}.{' '}
        {blocked ? <span>Import is off — {blocked}</span> : <span>Import is ready.</span>}
      </p>

      <label className={styles.toggle}>
        <input
          type="checkbox"
          checked={z.auto_approve.on}
          disabled={!canAdmin || busy || !z.auto_approve.master}
          onChange={(e) => void flip(e.target.checked)}
        />{' '}
        Approve imported questions automatically when they pass every strict check
        {!z.auto_approve.master && <span className={styles.hint}> (switched off for this server)</span>}
      </label>
      <p className={styles.hint}>
        {z.auto_approve.on
          ? 'Anything unsure, unclear or duplicated is saved as a draft instead. You can retire a question at any time, or send a whole import back to draft.'
          : 'Every imported question is saved as a draft for a trainer to approve.'}
      </p>

      <label className={styles.toggle}>
        <input
          type="checkbox"
          checked={top.on}
          disabled={!canAdmin || busy || !top.master}
          onChange={(e) => void flipTopUp(e.target.checked)}
        />{' '}
        Top up the question bank every night
        {!top.master && <span className={styles.hint}> (switched off for this server)</span>}
      </label>
      <p className={styles.hint}>
        {top.on
          ? `Each night, if fewer than ${options.bank.target} questions are approved, up to ${top.count} past tickets are imported with the same checks as a manual import. Next check: ${formatDateTime(top.next_run_at)}.`
          : 'Off. When it is on, the bank is topped up from past customer queries each night when it runs short. It never runs without an administrator turning it on.'}
        {top.on && blocked && ' It will do nothing until importing is ready (see above).'}
      </p>
      {top.on && top.paused && (
        <p className={styles.problem} role="status">
          Paused: the last few nights found nothing new. Run an import yourself, or switch this off and on, to resume.
        </p>
      )}
      {top.on && top.last_check && !top.paused && (
        <p className={styles.hint}>
          Last check {formatDateTime(top.last_check.at)}: {top.last_check.outcome === 'queued' ? 'ran' : 'did nothing'} —{' '}
          {top.last_check.reason}
        </p>
      )}

      {problem && (
        <p className={styles.problem} role="alert">
          {problem}
        </p>
      )}

      {rows.length > 0 && (
        <ul className={styles.runs} aria-label="Recent imports">
          {rows.slice(0, 3).map((r) => (
            <li key={r.id}>
              <p>
                <strong>Import #{r.id}</strong> · {r.state_label.toLowerCase()} · {formatWhen(r.created_at)}
                {r.trigger === 'scheduled' ? ' · nightly top-up' : r.started_by ? ` · ${r.started_by}` : ''}
              </p>
              <p className={styles.hint}>
                {active(r)
                  ? `Working… ${r.examined} looked at so far.`
                  : `${r.examined} past tickets looked at · ${summary(r)}`}
                {r.error && <span className={styles.problem}> {r.error}</span>}
              </p>
              {!active(r) && Object.keys(r.rejected).length > 0 && (
                <ul className={styles.reasons} aria-label={`Not used in import ${r.id}`}>
                  {Object.entries(r.rejected).map(([reason, n]) => (
                    <li key={reason}>
                      {n} not used: {labelFor(reason)}
                    </li>
                  ))}
                </ul>
              )}
              <p className={styles.runActions}>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => onShowRun(r.id)}>
                  Show these questions
                </button>
                {canAdmin && r.approved_now > 0 && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={() => setConfirming(r)}
                  >
                    Send {r.approved_now} back to draft
                  </button>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}

      {dialog && (
        <ImportDialog
          options={options}
          onClose={() => setDialog(false)}
          onStarted={() => {
            setDialog(false)
            onImported('Import started. It runs in the background — the result appears below.')
            runs.reload()
          }}
        />
      )}
      {confirming && (
        <Dialog
          title="Send this import back to draft?"
          width={460}
          role="alertdialog"
          onClose={() => setConfirming(null)}
          actions={
            <>
              <button type="button" className="btn" onClick={() => setConfirming(null)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" onClick={() => void revert(confirming)}>
                Send them back
              </button>
            </>
          }
        >
          {confirming.approved_now} {confirming.approved_now === 1 ? 'question' : 'questions'} that import approved
          automatically will stop being given to learners until a trainer approves them again. Anything a person
          approved is left alone.
        </Dialog>
      )}
    </section>
    </>
  )
}

function ImportDialog({
  options,
  onClose,
  onStarted,
}: {
  options: PracticeOptions
  onClose: () => void
  onStarted: () => void
}) {
  const [count, setCount] = useState('10')
  const [topic, setTopic] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const max = options.import_max
  const n = Number(count)
  const valid = Number.isInteger(n) && n >= 1 && n <= max

  async function start() {
    setBusy(true)
    setProblem(null)
    try {
      await adminApi.startImport({ count: n, ...(topic ? { topic } : {}) })
      onStarted()
    } catch (err) {
      setProblem(err instanceof ApiError && err.message ? err.message : 'That didn’t start. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      title="Import from past customer queries"
      width={560}
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" disabled={busy || !valid} onClick={() => void start()}>
            {busy ? 'Starting…' : 'Import'}
          </button>
        </>
      }
    >
      <div className={styles.form}>
        <p className={styles.hint}>
          We read a random sample of closed tickets from your Query forms and keep only the ones a customer typed
          themselves. The AI model then sees each message — with names, emails, numbers and links removed first — and
          rewrites it as a practice question without any personal detail. The customer’s original wording is not kept.
        </p>
        <div className={styles.row}>
          <div className={styles.field}>
            <label htmlFor="imp-count">{`How many questions (1–${max})`}</label>
            <input
              id="imp-count"
              className="input"
              type="number"
              min={1}
              max={max}
              value={count}
              onChange={(e) => setCount(e.target.value)}
            />
          </div>
          <div className={styles.field}>
            <label htmlFor="imp-topic">Only this topic</label>
            <select id="imp-topic" className="input" value={topic} onChange={(e) => setTopic(e.target.value)}>
              <option value="">Any topic</option>
              {options.topics.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label.split(' — ')[0]}
                </option>
              ))}
            </select>
          </div>
        </div>
        {problem && (
          <p className={styles.problem} role="alert">
            {problem}
          </p>
        )}
      </div>
    </Dialog>
  )
}
