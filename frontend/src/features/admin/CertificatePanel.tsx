import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Dialog } from '../../components/Dialog'
import { adminApi, type CertificatePage, type CertificationStanding } from './adminApi'
import { formatDateTime, percent } from './format'
import page from './enrollment.module.css'
import people from './people.module.css'
import styles from './results.module.css'

const KIND_LABEL = { quiz: 'Quizzes', practice: 'Practice tickets', rated: 'Mentor-rated work' }

interface Props {
  learner: string
  standing: CertificationStanding
  /** Required lessons not finished yet. */
  lessonsLeft: number
  /** Their certificate on this course, live or revoked, if they have ever had one. */
  cert: CertificatePage | null
  canManage: boolean
  onChanged: () => void
}

/** The course score behind the certificate, how it is made up, and the certificate itself
 * (with revoke / restore for people who manage enrollments). */
export function CertificatePanel({
  learner,
  standing,
  lessonsLeft,
  cert,
  canManage,
  onChanged,
}: Props) {
  const [revoking, setRevoking] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  if (!standing.enabled && !cert) return null

  async function act(run: () => Promise<unknown>) {
    setBusy(true)
    setProblem(null)
    try {
      await run()
      setRevoking(false)
      setReason('')
      onChanged()
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'That didn’t work.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.certificate} aria-label="Certificate">
      <div className={styles.certMain}>
        <h3 className={styles.blockTitle}>Certificate</h3>
        {cert && !cert.revoked ? (
          <p>
            <strong className={styles.s_completed}>Earned</strong> on{' '}
            {formatDateTime(cert.issued_at)} with{' '}
            {cert.score === null ? 'no scored work' : percent(cert.score)} (needed {cert.threshold}
            %) · <Link to={`/certificates/${cert.code}`}>{cert.code}</Link>
          </p>
        ) : cert?.revoked ? (
          <p>
            <strong>Revoked</strong>
            {cert.revoked_at ? ` on ${formatDateTime(cert.revoked_at)}` : ''}
            {cert.revoked_reason ? ` — ${cert.revoked_reason}` : ''}
          </p>
        ) : standing.enabled ? (
          <p>
            Not earned yet
            {lessonsLeft > 0
              ? ` — ${lessonsLeft} required ${lessonsLeft === 1 ? 'lesson' : 'lessons'} left.`
              : '.'}{' '}
            {standing.score === null
              ? `No scored work yet; the pass mark is ${standing.threshold}%.`
              : `Course score so far ${percent(standing.score)} (pass mark ${standing.threshold}%).`}
            {standing.missing.length > 0 &&
              ` Still needs a result in: ${standing.missing.map((k) => KIND_LABEL[k].toLowerCase()).join(', ')}.`}
          </p>
        ) : null}
        {standing.enabled && standing.parts && (
          <ul className={styles.parts} aria-label="How the course score is made up">
            {(['quiz', 'practice', 'rated'] as const)
              .filter((k) => standing.parts![k].items > 0)
              .map((k) => {
                const p = standing.parts![k]
                return (
                  <li key={k}>
                    <span>{KIND_LABEL[k]}</span>
                    <strong>{p.average === null ? '—' : percent(p.average)}</strong>
                    <span className={styles.sub}>
                      {p.scored} of {p.items} with a result ·{' '}
                      {p.weight === 0 ? 'not counted' : `weight ${p.weight}`}
                    </span>
                  </li>
                )
              })}
          </ul>
        )}
      </div>
      {canManage && cert && (
        <div>
          {cert.revoked ? (
            <button
              type="button"
              className="btn btn-sm"
              disabled={busy}
              onClick={() => void act(() => adminApi.restoreCertificate(cert.id!))}
            >
              Restore
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setRevoking(true)}
            >
              Revoke
            </button>
          )}
        </div>
      )}
      {problem && !revoking && (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      )}
      {revoking && cert && (
        <Dialog
          title="Revoke this certificate?"
          role="alertdialog"
          width={460}
          onClose={() => setRevoking(false)}
          actions={
            <>
              <button type="button" className="btn" onClick={() => setRevoking(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-danger"
                disabled={busy || !reason.trim()}
                onClick={() => void act(() => adminApi.revokeCertificate(cert.id!, reason))}
              >
                {busy ? 'Working…' : 'Revoke'}
              </button>
            </>
          }
        >
          <div className={page.stack}>
            <p>
              {learner} will no longer see certificate {cert.code}, and it won’t be issued again by
              itself. You can restore it later. This is recorded in the audit log.
            </p>
            <label className={people.field}>
              <span>Reason</span>
              <textarea
                className="input"
                rows={3}
                maxLength={300}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            {problem && (
              <p role="alert" className={people.problem}>
                {problem}
              </p>
            )}
          </div>
        </Dialog>
      )}
    </div>
  )
}
