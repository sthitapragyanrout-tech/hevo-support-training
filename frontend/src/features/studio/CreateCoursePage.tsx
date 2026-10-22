import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { studioApi } from './studioApi'
import styles from './CreateCoursePage.module.css'

export function CreateCoursePage() {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!title.trim()) {
      setError('Give the course a title.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const course = await studioApi.createCourse(title.trim(), description.trim())
      navigate(`/studio/courses/${course.id}/curriculum`, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Couldn’t create the course.')
      setBusy(false)
    }
  }

  return (
    <div className={styles.wrap}>
      <form className={styles.page} onSubmit={submit}>
        <Link to="/studio" className={styles.back}>
          <Icon name="arrowLeft" size={14} /> Courses
        </Link>
        <h1>Create a course</h1>
        <p className={styles.lead}>
          Start with a title. You’ll add modules and lessons next — or import them from a
          spreadsheet.
        </p>

        <label className={styles.field}>
          Course title
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. CX Onboarding 2026"
            autoFocus
            maxLength={255}
          />
        </label>

        <label className={styles.field}>
          <span>
            What is this course for? <span className={styles.optional}>Optional</span>
          </span>
          <textarea
            className="textarea"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
            placeholder="One or two sentences on what learners will be able to do afterwards."
          />
        </label>

        {error && (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        )}

        <div className={styles.actions}>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? 'Creating…' : 'Create course'}
          </button>
          <Link to="/studio" className="btn btn-ghost">
            Cancel
          </Link>
        </div>
      </form>
    </div>
  )
}
