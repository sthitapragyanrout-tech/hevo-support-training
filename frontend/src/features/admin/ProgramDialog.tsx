import { useState } from 'react'

import { Dialog } from '../../components/Dialog'
import { adminApi, type EnrollOptions, type ProgramRow } from './adminApi'
import styles from './people.module.css'
import page from './enrollment.module.css'

interface Props {
  program: ProgramRow | null
  courses: EnrollOptions['courses']
  onClose: () => void
  onSaved: (message: string) => void
}

interface Item {
  id: number
  title: string
  required: boolean
}

/** Create or edit a program: its name, dates, and its courses in order. */
export function ProgramDialog({ program, courses, onClose, onSaved }: Props) {
  const [name, setName] = useState(program?.name ?? '')
  const [description, setDescription] = useState(program?.description ?? '')
  const [startsOn, setStartsOn] = useState(program?.starts_on ?? '')
  const [endsOn, setEndsOn] = useState(program?.ends_on ?? '')
  const [items, setItems] = useState<Item[]>(
    program?.courses.map((c) => ({ id: c.course_id, title: c.title, required: c.required })) ?? [],
  )
  const [adding, setAdding] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const available = courses.filter((c) => !items.some((i) => i.id === c.id))

  function move(index: number, by: -1 | 1) {
    setItems((list) => {
      const next = [...list]
      const to = index + by
      if (to < 0 || to >= next.length) return list
      ;[next[index], next[to]] = [next[to], next[index]]
      return next
    })
  }

  async function save() {
    setBusy(true)
    setProblem(null)
    const body = {
      name,
      description,
      starts_on: startsOn || null,
      ends_on: endsOn || null,
      courses: items.map((i) => ({ course_id: i.id, required: i.required })),
    }
    try {
      if (program) await adminApi.updateProgram(program.id, body)
      else await adminApi.createProgram(body)
      onSaved(program ? `${name} is saved.` : `${name} is created.`)
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'We couldn’t save the group.')
      setBusy(false)
    }
  }

  return (
    <Dialog
      title={program ? `Edit ${program.name}` : 'New group'}
      width={560}
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || !name.trim()}
            onClick={() => void save()}
          >
            {busy ? 'Saving…' : 'Save'}
          </button>
        </>
      }
    >
      <div className={page.stack}>
        <label className={styles.field}>
          <span>Name</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className={styles.field}>
          <span>Description (optional)</span>
          <input
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <div className={styles.pair}>
          <label className={styles.field}>
            <span>Starts (optional)</span>
            <input
              type="date"
              className="input"
              value={startsOn}
              onChange={(e) => setStartsOn(e.target.value)}
            />
          </label>
          <label className={styles.field}>
            <span>Ends (optional)</span>
            <input
              type="date"
              className="input"
              value={endsOn}
              onChange={(e) => setEndsOn(e.target.value)}
            />
          </label>
        </div>

        <div className={page.stack}>
          <span className={styles.sub}>Courses, in order</span>
          {items.length === 0 ? (
            <p className={page.muted}>
              No courses yet. Add the courses learners take in this group.
            </p>
          ) : (
            <ol className={page.courseRows}>
              {items.map((item, index) => (
                <li key={item.id}>
                  <span>
                    {index + 1}. {item.title}
                  </span>
                  <span className={styles.buttons}>
                    <label>
                      <input
                        type="checkbox"
                        checked={item.required}
                        onChange={(e) =>
                          setItems((list) =>
                            list.map((i) =>
                              i.id === item.id ? { ...i, required: e.target.checked } : i,
                            ),
                          )
                        }
                      />
                      Required
                    </label>
                    <button
                      type="button"
                      className="btn btn-sm"
                      aria-label={`Move ${item.title} up`}
                      disabled={index === 0}
                      onClick={() => move(index, -1)}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm"
                      aria-label={`Move ${item.title} down`}
                      disabled={index === items.length - 1}
                      onClick={() => move(index, 1)}
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm"
                      aria-label={`Remove ${item.title}`}
                      onClick={() => setItems((list) => list.filter((i) => i.id !== item.id))}
                    >
                      Remove
                    </button>
                  </span>
                </li>
              ))}
            </ol>
          )}
          {available.length > 0 && (
            <select
              className="input"
              aria-label="Add a course"
              value={adding}
              onChange={(e) => {
                const found = courses.find((c) => String(c.id) === e.target.value)
                if (found)
                  setItems((list) => [
                    ...list,
                    { id: found.id, title: found.title, required: true },
                  ])
                setAdding('')
              }}
            >
              <option value="">Add a course…</option>
              {available.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
          )}
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
