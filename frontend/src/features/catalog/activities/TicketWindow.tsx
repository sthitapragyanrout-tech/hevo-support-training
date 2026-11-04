import { useEffect, useState } from 'react'

import { Dialog } from '../../../components/Dialog'
import type { SimSession, SkipReason } from '../../../lib/api'
import styles from './SimActivity.module.css'
import { SimResults } from './SimResults'
import { Thread } from './TicketThread'
import { useTicketSession } from './useTicketSession'

const MAX_CHARS = 4000

const SKIP_REASONS: { value: SkipReason; label: string }[] = [
  { value: 'duplicate', label: 'I’ve already had a question like this' },
  { value: 'unclear', label: 'It’s unclear or doesn’t make sense' },
  { value: 'not_relevant', label: 'It’s not relevant to the job' },
]

function minutes(since: string | null, now: number): number | null {
  if (!since) return null
  return Math.max(0, Math.floor((now - new Date(since).getTime()) / 60_000))
}

const ENDED: Record<string, string> = {
  too_short:
    'This ticket ended before there was enough to score, so it didn’t count as an attempt. You can start again.',
  timed_out: 'This ticket timed out with no reply, so it didn’t count as an attempt. You can start again.',
  no_replies: 'You ended this ticket before replying, so it didn’t count as an attempt.',
  skipped: 'You skipped that question. It doesn’t count, and you won’t be given it again.',
  reset: 'Your trainer reset this ticket.',
  token_budget: 'This ticket reached its length limit and didn’t count as an attempt.',
  attempts_unavailable: 'This ticket couldn’t be recorded (your attempts had changed). Ask your trainer.',
  feedback_failed:
    'We couldn’t prepare feedback for this ticket, so it didn’t count as an attempt. You can start again.',
}

/** After this long "Finishing…" is no longer "a few seconds", and we say so. */
const SLOW_FINISH_MS = 60_000

interface Props {
  initial: SimSession
  /** Is this attempt recorded? False in an author's preview. */
  title?: string
  canTryAgain: boolean
  /** How many more questions this learner may skip (0 hides the option). */
  skipsLeft?: number
  onTryAgain: () => void
  onSettled: (s: SimSession) => void
  onClose: () => void
}

/** The practice ticket in its own window: the customer's message, your reply,
 * and (when it's over) your result. Closing the window doesn't end the ticket —
 * it waits for you, and the customer's clock keeps running, like a real inbox. */
export function TicketWindow({
  initial,
  title,
  canTryAgain,
  skipsLeft = 0,
  onTryAgain,
  onSettled,
  onClose,
}: Props) {
  const ticket = useTicketSession(initial, onSettled)
  const { session } = ticket
  const [draft, setDraft] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [skipping, setSkipping] = useState(false)
  const [skipReason, setSkipReason] = useState<SkipReason | ''>('')
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(t)
  }, [])

  const [finishingSince, setFinishingSince] = useState<number | null>(null)
  useEffect(() => {
    setFinishingSince(session.state === 'finishing' ? Date.now() : null)
  }, [session.state])
  const slowFinish = finishingSince != null && now - finishingSince >= SLOW_FINISH_MS

  const waited = session.can_reply ? minutes(session.customer_waiting_since, now) : null
  const preview = session.preview
  const left = session.max_exchanges - session.exchanges

  async function send() {
    const text = draft.trim()
    if (!text || ticket.busy) return
    if (await ticket.send(text)) setDraft('')
  }

  async function finish() {
    setConfirming(false)
    await ticket.finish()
  }

  async function skip() {
    if (!skipReason) return
    setSkipping(false)
    await ticket.skip(skipReason)
  }

  const open = session.state === 'open'
  const canSkip = open && !preview && session.exchanges === 0 && skipsLeft > 0
  const actions = open ? (
    <>

      <button type="button" className="btn" onClick={() => setConfirming(true)} disabled={ticket.busy}>
        Finish ticket
      </button>
      <button type="button" className="btn btn-primary" onClick={onClose}>
        Close
      </button>
    </>
  ) : (
    <button type="button" className="btn btn-primary" onClick={onClose}>
      Close
    </button>
  )

  return (
    <>
      <Dialog title={title ?? 'Practice ticket'} width={760} onClose={onClose} actions={actions}>
        <div className={styles.window}>
          {preview && (
            <p className={styles.banner} role="note">
              Preview — nothing you do here is scored or recorded.
            </p>
          )}
          <div className={styles.ticketHead}>
            <p className={styles.subject}>{session.subject}</p>
            {open && (
              <span className={styles.count}>
                Reply {Math.min(session.exchanges + 1, session.max_exchanges)} of {session.max_exchanges}
              </span>
            )}
          </div>

          {(open || session.state === 'finishing') && <Thread items={session.thread} follow finishing={session.state === 'finishing'} />}

          {open && session.can_reply && (
            <div className={styles.composer}>
              <label htmlFor="sim-reply" className="eyebrow">
                Your reply
              </label>
              <textarea
                id="sim-reply"
                className="input"
                value={draft}
                maxLength={MAX_CHARS}
                disabled={ticket.busy}
                placeholder="Write your reply as you would in a ticket…"
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') void send()
                }}
              />
              <div className={styles.composerFoot}>
                <span className={styles.status}>
                  {waited !== null && waited >= 1 ? `The customer has been waiting ${waited} min. ` : ''}
                  {left > 1 ? `${left} replies left.` : left === 1 ? 'Last reply.' : ''}
                  {canSkip && (
                    <>
                      {' '}
                      <button
                        type="button"
                        className={styles.linkButton}
                        onClick={() => setSkipping(true)}
                        disabled={ticket.busy}
                      >
                        Skip this question
                      </button>
                    </>
                  )}
                </span>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={!draft.trim() || ticket.busy}
                  onClick={() => void send()}
                >
                  {ticket.busy ? 'Sending…' : 'Send reply'}
                </button>
              </div>
            </div>
          )}

          {open && session.waiting_for_customer && (
            <p className={styles.pending} role="status">
              <span className={styles.spinner} aria-hidden="true" />
              The customer is replying…
            </p>
          )}

          {open && session.failed && (
            <div role="alert">
              <p className={styles.problem}>{session.failed_message || 'The customer couldn’t reply just now.'}</p>
              <button type="button" className="btn btn-sm" disabled={ticket.busy} onClick={() => void ticket.retry()}>
                Try again
              </button>
            </div>
          )}

          {session.state === 'finishing' && (
            <p className={styles.pending} role="status">
              <span className={styles.spinner} aria-hidden="true" />
              {slowFinish
                ? 'This is taking longer than usual. You can leave this page; we’ll keep trying.'
                : session.exchanges >= 2
                  ? 'Preparing your feedback… this usually takes a few seconds.'
                  : 'Finishing this ticket… this usually takes a few seconds.'}
            </p>
          )}

          {session.state === 'finished' && session.result && (
            <SimResults session={session} result={session.result} canTryAgain={canTryAgain} onTryAgain={onTryAgain} />
          )}

          {session.state === 'abandoned' && (
            <div>
              <p className={styles.feedback} role="status">
                {ENDED[session.abandoned_reason] ?? 'This ticket ended without a score.'}
              </p>
              {canTryAgain && (
                <p>
                  <button type="button" className="btn btn-primary btn-sm" onClick={onTryAgain}>
                    {session.abandoned_reason === 'skipped' ? 'Next question' : 'Start again'}
                  </button>
                </p>
              )}
            </div>
          )}

          {ticket.problem && (
            <p className={styles.problem} role="alert">
              {ticket.problem}
            </p>
          )}
        </div>
      </Dialog>

      {skipping && (
        <Dialog
          title="Skip this question?"
          width={460}
          role="alertdialog"
          onClose={() => setSkipping(false)}
          actions={
            <>
              <button type="button" className="btn" onClick={() => setSkipping(false)}>
                Keep it
              </button>
              <button type="button" className="btn btn-primary" disabled={!skipReason} onClick={() => void skip()}>
                Skip this question
              </button>
            </>
          }
        >
          <p>
            It won’t count, and you won’t be given it again. You can skip {skipsLeft}{' '}
            {skipsLeft === 1 ? 'more question' : 'more questions'} on this activity. Why are you skipping it?
          </p>
          <fieldset className={styles.reasons}>
            <legend className="sr-only">Why are you skipping it?</legend>
            {SKIP_REASONS.map((r) => (
              <label key={r.value}>
                <input
                  type="radio"
                  name="skip-reason"
                  value={r.value}
                  checked={skipReason === r.value}
                  onChange={() => setSkipReason(r.value)}
                />{' '}
                {r.label}
              </label>
            ))}
          </fieldset>
        </Dialog>
      )}

      {confirming && (
        <Dialog
          title="Finish this ticket?"
          width={440}
          role="alertdialog"
          onClose={() => setConfirming(false)}
          actions={
            <>
              <button type="button" className="btn" onClick={() => setConfirming(false)}>
                Keep going
              </button>
              <button type="button" className="btn btn-primary" onClick={() => void finish()}>
                {session.exchanges >= 2 ? 'Finish and see my score' : 'Finish without a score'}
              </button>
            </>
          }
        >
          {session.exchanges >= 2
            ? `You’ve sent ${session.exchanges} replies. Finishing now scores what you’ve written so far.`
            : session.exchanges === 1
              ? 'You’ve sent 1 reply — that’s too little to score, so this ticket won’t count as an attempt.'
              : 'You haven’t replied yet, so this ticket won’t count as an attempt.'}
        </Dialog>
      )}
    </>
  )
}
