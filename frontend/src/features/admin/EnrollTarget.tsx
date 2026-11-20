import type { EnrollOptions } from './adminApi'
import type { Target } from './targetModel'
import styles from './people.module.css'
import page from './enrollment.module.css'

interface Props {
  options: EnrollOptions
  target: Target
  onTarget: (target: Target) => void
  mentor: string
  onMentor: (mentor: string) => void
  /** "Mentor" for one person; the default for everyone on a list. */
  mentorLabel?: string
}

/** What to enrol people on — a course or a whole program — and an optional mentor. */
export function EnrollTarget({
  options,
  target,
  onTarget,
  mentor,
  onMentor,
  mentorLabel = 'Mentor (optional)',
}: Props) {
  const programs = options.programs.filter((p) => p.course_ids.length > 0)
  return (
    <div className={page.stack}>
      <fieldset className={page.choices}>
        <legend className="sr-only">Enroll on</legend>
        <label>
          <input
            type="radio"
            name="target-kind"
            checked={target.kind === 'course'}
            onChange={() => onTarget({ kind: 'course', id: '' })}
          />
          A course
        </label>
        <label>
          <input
            type="radio"
            name="target-kind"
            checked={target.kind === 'program'}
            onChange={() => onTarget({ kind: 'program', id: '' })}
          />
          A whole group
        </label>
      </fieldset>
      <label className={styles.field}>
        <span>{target.kind === 'course' ? 'Course' : 'Group'}</span>
        <select
          className="input"
          value={target.id}
          onChange={(e) => onTarget({ ...target, id: e.target.value })}
        >
          <option value="">
            {target.kind === 'course' ? 'Choose a course' : 'Choose a group'}
          </option>
          {target.kind === 'course'
            ? options.courses.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))
            : programs.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.course_ids.length} {p.course_ids.length === 1 ? 'course' : 'courses'}
                  )
                </option>
              ))}
        </select>
      </label>
      <label className={styles.field}>
        <span>{mentorLabel}</span>
        <select className="input" value={mentor} onChange={(e) => onMentor(e.target.value)}>
          <option value="">No mentor — work goes to the shared pool</option>
          {options.mentors.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
