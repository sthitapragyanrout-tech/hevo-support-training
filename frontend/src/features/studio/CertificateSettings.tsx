import { useEffect, useState } from 'react'

import { studioApi, type CertificatePolicy } from './studioApi'
import styles from './SettingsTab.module.css'

type Kind = keyof CertificatePolicy['weights']

const KINDS: { key: Kind; label: string }[] = [
  { key: 'quiz', label: 'Quizzes' },
  { key: 'practice', label: 'Practice tickets' },
  { key: 'rated', label: 'Mentor-rated work' },
]

/** Whether finishing this course earns a certificate, and the course score it takes. A course
 * setting, not part of a version: it applies straight away, without publishing. */
export function CertificateSettings({ courseId }: { courseId: number }) {
  const [saved, setSaved] = useState<CertificatePolicy | null>(null)
  const [form, setForm] = useState<CertificatePolicy | null>(null)
  const [loadProblem, setLoadProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    studioApi
      .certificatePolicy(courseId)
      .then((p) => {
        if (!live) return
        setSaved(p)
        setForm(p)
      })
      .catch((err) => live && setLoadProblem(err instanceof Error ? err.message : 'Not loaded.'))
    return () => {
      live = false
    }
  }, [courseId])

  if (loadProblem) {
    return (
      <p role="alert" className={styles.problem}>
        We couldn’t load the certificate settings. {loadProblem}
      </p>
    )
  }
  if (!form || !saved) return <p className={styles.note}>Loading…</p>

  const changed =
    form.enabled !== saved.enabled ||
    form.threshold !== saved.threshold ||
    KINDS.some((k) => form.weights[k.key] !== saved.weights[k.key])

  async function save() {
    if (!form) return
    setBusy(true)
    setProblem(null)
    setMessage(null)
    try {
      const next = await studioApi.saveCertificatePolicy(courseId, {
        enabled: form.enabled,
        threshold: form.threshold,
        weights: form.weights,
      })
      setSaved(next)
      setForm(next)
      setMessage(
        next.enabled
          ? 'Saved. Everyone on the course is checked again now.'
          : 'Saved. No new certificates will be issued.',
      )
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t save that.')
    } finally {
      setBusy(false)
    }
  }

  const number = (value: string) => (value === '' ? 0 : Math.trunc(Number(value)))

  return (
    <form
      className={styles.cert}
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        void save()
      }}
    >
      <label className={styles.option}>
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
        />
        <span>
          <strong>Learners earn a certificate on this course</strong>
          <span className={styles.hint}>
            Issued automatically once every required lesson is done and the course score reaches the
            passing threshold. A certificate is never taken back by a later change here.
          </span>
        </span>
      </label>

      <fieldset className={styles.certFields} disabled={!form.enabled}>
        <legend className="sr-only">Score settings</legend>
        <label className={styles.inlineField}>
          <span>Passing threshold</span>
          <span className={styles.suffix}>
            <input
              className="input"
              type="number"
              min={1}
              max={100}
              step={1}
              value={form.threshold}
              aria-label="Passing threshold (%)"
              onChange={(e) => setForm({ ...form, threshold: number(e.target.value) })}
            />
            %
          </span>
        </label>
        <div>
          <p className={styles.fieldLabel}>How the course score is made up</p>
          <p className={styles.hint}>
            Each kind of work is averaged (quizzes by best score, practice tickets by their average,
            mentor-rated work by its latest rating), then combined by these weights. A kind the
            course doesn’t have is skipped; 0 leaves it out.
          </p>
          <div className={styles.weights}>
            {KINDS.map((k) => (
              <label key={k.key} className={styles.inlineField}>
                <span>{k.label}</span>
                <input
                  className="input"
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={form.weights[k.key]}
                  aria-label={`Weight for ${k.label.toLowerCase()}`}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      weights: { ...form.weights, [k.key]: number(e.target.value) },
                    })
                  }
                />
              </label>
            ))}
          </div>
        </div>
      </fieldset>

      <p className={styles.note}>
        This applies straight away, to everyone on the course; it doesn’t need publishing.
      </p>
      {problem && (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      )}
      {message && !changed && (
        <p role="status" className={styles.note}>
          {message}
        </p>
      )}
      <div>
        <button type="submit" className="btn btn-primary" disabled={busy || !changed}>
          {busy ? 'Saving…' : 'Save certificate settings'}
        </button>
      </div>
    </form>
  )
}
