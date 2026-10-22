import { useId, useState } from 'react'

import { AutosaveField } from './AutosaveField'
import { useConfigWriter } from './useConfigWriter'
import type { JsonSchema } from './types'
import styles from './SchemaForm.module.css'

type Config = Record<string, unknown>

interface Props {
  schema: JsonSchema
  value: Config
  disabled?: boolean
  /** Persist the whole new config; reject with an Error to show its message. */
  onChange: (next: Config) => Promise<void>
}

/** Generic form for any activity type, generated from its JSON Schema — no
 * per-type code. Simple fields get inputs; anything structured (a quiz's
 * question list) gets a validated JSON box until that type ships its own
 * editor. */
export function SchemaForm({ schema, value, disabled, onChange }: Props) {
  // Several fields can be edited before the first save returns; see the hook.
  const write = useConfigWriter(value, onChange)
  const properties = Object.entries(schema.properties ?? {})
  const required = new Set(schema.required ?? [])

  if (properties.length === 0) {
    return <p className={styles.none}>This activity type has no settings yet.</p>
  }

  return (
    <div className={styles.form}>
      {properties.map(([key, prop]) => (
        <SchemaField
          key={key}
          name={key}
          schema={prop}
          required={required.has(key)}
          disabled={disabled}
          value={value[key]}
          onCommit={(next) =>
            write((current) => {
              const config = { ...current }
              if (next === undefined) delete config[key]
              else config[key] = next
              return config
            })
          }
        />
      ))}
    </div>
  )
}

interface FieldProps {
  name: string
  schema: JsonSchema
  value: unknown
  required: boolean
  disabled?: boolean
  onCommit: (next: unknown) => Promise<void>
}

function SchemaField({ name, schema, value, required, disabled, onCommit }: FieldProps) {
  const id = useId()
  const label = schema.title ?? name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, ' ')
  const type = schema.type
  const structured = type === 'array' || type === 'object'

  const asText = structured
    ? JSON.stringify(value ?? (type === 'array' ? [] : {}), null, 2)
    : value === undefined || value === null
      ? ''
      : String(value)

  const [draft, setDraft] = useState(asText)
  const [shown, setShown] = useState(asText)
  const [error, setError] = useState<string | null>(null)
  if (asText !== shown) {
    setShown(asText)
    setDraft(asText)
  }

  async function commit(next: unknown) {
    setError(null)
    try {
      await onCommit(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Couldn’t save.')
    }
  }

  function blur() {
    if (draft === asText) return
    try {
      void commit(JSON.parse(draft))
    } catch {
      setError('That isn’t valid JSON.')
    }
  }

  // Plain text and number fields behave like every other Studio field: they
  // save as you leave them (or paste, or press Enter) and say "Saved".
  async function save(text: string) {
    if (type === 'integer' || type === 'number') {
      if (text.trim() === '') return onCommit(undefined)
      const n = Number(text)
      if (Number.isNaN(n)) throw new Error('Enter a number.')
      return onCommit(type === 'integer' ? Math.trunc(n) : n)
    }
    return onCommit(text)
  }

  if (type === 'boolean') {
    return (
      <div className={styles.field}>
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={value === true}
            disabled={disabled}
            onChange={(e) => void commit(e.target.checked)}
          />
          {label}
        </label>
        {error && <p className={styles.error}>{error}</p>}
      </div>
    )
  }

  if (!structured) {
    const isNumber = type === 'integer' || type === 'number'
    return (
      <AutosaveField
        label={
          <>
            {label}
            {required && (
              <span className={styles.req} title="Required to publish">
                {' '}
                *<span className="sr-only"> required</span>
              </span>
            )}
          </>
        }
        value={asText}
        type={isNumber ? 'number' : 'text'}
        disabled={disabled}
        onSave={save}
      />
    )
  }

  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
        {required && (
          <span className={styles.req} title="Required to publish">
            {' '}
            *<span className="sr-only"> required</span>
          </span>
        )}
      </label>
      <textarea
        id={id}
        className={`${styles.control} ${styles.code}`}
        rows={Math.min(14, Math.max(4, draft.split('\n').length))}
        value={draft}
        disabled={disabled}
        spellCheck={false}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={blur}
      />
      {error && <p className={styles.error}>{error}</p>}
    </div>
  )
}
