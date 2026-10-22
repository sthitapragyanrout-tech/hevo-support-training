import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { useBuilder } from './builderContext'
import styles from './ImportTab.module.css'
import { studioApi } from './studioApi'
import type { ImportOutlineNode, ImportPreview } from './types'

const FIELD_LABELS: Record<string, string> = {
  module: 'Module',
  lesson: 'Lesson',
  section: 'Section',
  description: 'Description',
  minutes: 'Minutes',
  activity: 'Activity title',
  activity_type: 'Activity type',
  required: 'Required?',
  points: 'Points',
  url: 'Link (URL)',
}

function Outline({ nodes }: { nodes: ImportOutlineNode[] }) {
  return (
    <ul className={styles.outline}>
      {nodes.map((node, i) => (
        <li key={`${node.title}-${i}`}>
          <span className={`${styles.node} ${styles[node.level]}`}>{node.title}</span>
          {node.activities.length > 0 && (
            <span className={styles.acts}>
              {node.activities.map((a) => `${a.title || a.type}`).join(' · ')}
            </span>
          )}
          {node.children.length > 0 && <Outline nodes={node.children} />}
        </li>
      ))}
    </ul>
  )
}

/** Spreadsheet → validated preview → new content in the draft. The sheet is
 * read once; after import the course is managed here, not in the file. */
export function ImportTab() {
  const { course, apply } = useBuilder()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<ImportPreview['counts'] | null>(null)

  async function run(nextFile: File, mapping?: Record<string, string | null>) {
    setBusy(true)
    setError(null)
    setDone(null)
    try {
      setPreview(await studioApi.importPreview(course.id, nextFile, mapping))
    } catch (err) {
      setPreview(null)
      setError(err instanceof Error ? err.message : 'Couldn’t read that file.')
    } finally {
      setBusy(false)
    }
  }

  function choose(picked: File | undefined) {
    if (!picked) return
    setFile(picked)
    void run(picked)
  }

  async function commit() {
    if (!file || !preview) return
    setBusy(true)
    setError(null)
    try {
      const result = await studioApi.importCommit(course.id, file, preview.mapping)
      apply(result.course)
      setDone(result.counts)
      setPreview(null)
      setFile(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The import failed.')
    } finally {
      setBusy(false)
    }
  }

  if (!course.editable) {
    return (
      <p className={styles.locked}>
        Importing adds content to the draft. Start editing the course first, then come back.
      </p>
    )
  }

  const counts = preview?.counts
  const summary = counts
    ? [
        `${counts.modules} module${counts.modules === 1 ? '' : 's'}`,
        `${counts.lessons} lesson${counts.lessons === 1 ? '' : 's'}`,
        `${counts.sections} section${counts.sections === 1 ? '' : 's'}`,
        `${counts.activities} activit${counts.activities === 1 ? 'y' : 'ies'}`,
      ].join(' · ')
    : ''

  return (
    <div className={styles.page}>
      <section>
        <h2>1. Choose a spreadsheet</h2>
        <p className={styles.help}>
          A <strong>.csv</strong> or <strong>.xlsx</strong> file with one row per lesson or section.
          Columns like <em>Module, Lesson, Section, Minutes, Activity, Activity type</em> are
          recognised automatically; leave a cell blank to repeat the one above it. Imported
          content is added to this draft — the file isn’t kept.
        </p>
        <input
          ref={input}
          type="file"
          accept=".csv,.xlsx"
          className="sr-only"
          id="import-file"
          onChange={(e) => choose(e.target.files?.[0])}
        />
        <button type="button" className="btn" onClick={() => input.current?.click()} disabled={busy}>
          <Icon name="upload" size={16} /> {file ? 'Choose a different file' : 'Choose file'}
        </button>
        {file && <span className={styles.filename}>{file.name}</span>}
      </section>

      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}

      {done && (
        <div className={styles.success} role="status">
          <strong>Imported.</strong> Added {done.modules} modules, {done.lessons} lessons,{' '}
          {done.sections} sections and {done.activities} activities.{' '}
          <Link to={`/studio/courses/${course.id}/curriculum`}>Open the curriculum</Link>
        </div>
      )}

      {preview && (
        <>
          <section>
            <h2>2. Check the columns</h2>
            <div className={styles.mapping}>
              {Object.keys(FIELD_LABELS).map((field) => (
                <label key={field} className={styles.map}>
                  {FIELD_LABELS[field]}
                  <select
                    value={preview.mapping[field] ?? ''}
                    disabled={busy}
                    onChange={(e) =>
                      file &&
                      void run(file, { ...preview.mapping, [field]: e.target.value || null })
                    }
                  >
                    <option value="">— not in the file —</option>
                    {preview.headers.map((h) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          </section>

          <section>
            <h2>3. Review and import</h2>
            {preview.errors.length > 0 && (
              <div className={styles.problems} role="alert">
                <p>
                  <strong>
                    Fix {preview.errors.length} problem{preview.errors.length === 1 ? '' : 's'} in
                    the file, then choose it again:
                  </strong>
                </p>
                <ul>
                  {preview.errors.slice(0, 20).map((m, i) => (
                    <li key={i}>
                      {m.row ? <span className={styles.row}>Row {m.row}</span> : null} {m.message}
                    </li>
                  ))}
                </ul>
                {preview.errors.length > 20 && <p>…and {preview.errors.length - 20} more.</p>}
              </div>
            )}
            {preview.warnings.length > 0 && (
              <ul className={styles.warnings}>
                {preview.warnings.slice(0, 5).map((m, i) => (
                  <li key={i}>
                    {m.row ? <span className={styles.row}>Row {m.row}</span> : null} {m.message}
                  </li>
                ))}
              </ul>
            )}
            {preview.ok && (
              <>
                <p className={styles.counts}>{summary}</p>
                <Outline nodes={preview.outline} />
              </>
            )}
            <div className={styles.actions}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy || !preview.ok}
                onClick={() => void commit()}
              >
                {busy ? 'Working…' : 'Import into this course'}
              </button>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
