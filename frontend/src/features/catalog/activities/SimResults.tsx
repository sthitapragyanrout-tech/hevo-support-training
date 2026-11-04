import { useEffect, useRef, useState } from 'react'

import type { SimMetric, SimResult, SimSession, SimThreadItem } from '../../../lib/api'
import styles from './SimActivity.module.css'
import { outOf5 } from './simFormat'
import { Thread } from './TicketThread'

const BASIS_NOTE: Partial<Record<SimMetric['basis'], string>> = {
  model_judgment: 'AI-assessed',
  'link_check+model_relevance': 'Link checked · relevance AI-assessed',
  link_check: 'Link checked',
}

interface Props {
  session: SimSession
  result: SimResult
  /** Can the learner start another try right now? */
  canTryAgain: boolean
  onTryAgain: () => void
  /** Offer "View conversation" (the learner's own window does; the console shows it itself). */
  conversation?: boolean
}

/** How it went: the score out of 5 against the pass mark, six bars with a
 * sentence each, and the coach's note. Says plainly which numbers are checked
 * and which are an AI's opinion. */
export function SimResults({ session, result, canTryAgain, onTryAgain, conversation = true }: Props) {
  const [showThread, setShowThread] = useState(false)
  const ref = useRef<HTMLParagraphElement>(null)
  useEffect(() => ref.current?.focus(), [])
  const thread: SimThreadItem[] = session.thread
  const quota = result.quota
  const left = quota ? Math.max(quota.required - quota.done, 0) : null

  return (
    <div className={styles.results}>
      <div role="status">
        <p ref={ref} tabIndex={-1} className={styles.verdict}>
          {result.preview
            ? 'Preview'
            : result.passed
              ? 'Above the pass mark'
              : 'Below the pass mark'}
          <span className={styles.big}>
            {' '}
            · {outOf5(result.score.raw)} · pass mark {outOf5(result.pass_mark.raw)}
          </span>
        </p>
        <p className={styles.feedback}>
          {result.preview
            ? 'This was a preview — nothing was recorded.'
            : result.state === 'completed'
              ? `Well done — you’ve finished all ${quota?.required ?? ''} tickets, so this activity is complete.`
              : result.attempts_left === 0
                ? 'You’ve used all your tickets. You can continue with the lesson.'
                : quota && left !== null
                  ? `That’s ${quota.done} of ${quota.required} done — ${left} to go. ${
                      result.passed ? '' : 'It was below the pass mark, but it still counts. '
                    }Each ticket is a different question.`
                  : 'You can practise again with a new ticket.'}
        </p>
      </div>

      <ul className={styles.metrics} aria-label="Scores">
        {result.metrics.map((m) => (
          <li key={m.key}>
            <div className={styles.metricHead}>
              <span>
                {m.label}
                {BASIS_NOTE[m.basis] && <span className={styles.basis}>{BASIS_NOTE[m.basis]}</span>}
              </span>
              <span className={styles.metricValue}>{outOf5(m.raw)}</span>
            </div>
            <div
              className={styles.bar}
              role="meter"
              aria-label={m.label}
              aria-valuemin={0}
              aria-valuemax={m.max}
              aria-valuenow={m.raw}
            >
              <div className={styles.barFill} style={{ width: `${(m.raw / m.max) * 100}%` }} />
            </div>
            {m.feedback && <p className={styles.feedback}>{m.feedback}</p>}
          </li>
        ))}
      </ul>

      {result.narrative && (
        <section className={styles.narrative} aria-label="Feedback">
          {result.narrative.strengths && (
            <div>
              <h5>What went well</h5>
              <p>{result.narrative.strengths}</p>
            </div>
          )}
          {result.narrative.weaknesses && (
            <div>
              <h5>To work on</h5>
              <p>{result.narrative.weaknesses}</p>
            </div>
          )}
          {result.narrative.overall && <p>{result.narrative.overall}</p>}
        </section>
      )}

      {!result.grounded && (
        <p className={styles.honest}>
          Scores marked “AI-assessed” are an AI’s judgment against general knowledge — they haven’t
          been checked against Hevo’s documentation. Your trainer can review any result.
        </p>
      )}

      <div className={styles.footer}>
        {canTryAgain && (
          <button type="button" className="btn btn-primary btn-sm" onClick={onTryAgain}>
            Next ticket
          </button>
        )}
        {conversation && (
          <button
            type="button"
            className="btn btn-sm"
            aria-expanded={showThread}
            onClick={() => setShowThread((v) => !v)}
          >
            {showThread ? 'Hide conversation' : 'View conversation'}
          </button>
        )}
      </div>
      {showThread && <Thread items={thread} />}
    </div>
  )
}
