import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

import styles from './AutosaveField.module.css'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

interface Props {
  label: ReactNode
  value: string
  onSave: (value: string) => Promise<void>
  multiline?: boolean
  rows?: number
  type?: 'text' | 'number'
  placeholder?: string
  hint?: string
  disabled?: boolean
  /** Visually hide the label (it stays available to assistive tech). */
  hideLabel?: boolean
  /** Reject empty values (e.g. titles). */
  required?: boolean
  size?: 'normal' | 'title' | 'section'
  /** `ghost`: no visible box until hover/focus (for titles on the canvas). */
  ghost?: boolean
  /** Tight layout for list rows: no reserved space for the status line. */
  compact?: boolean
}

/** A field that saves itself — when you leave it, press Enter, or paste into
 * it — and says so. Quiet: the "Saved" note appears only after a real save
 * and fades on its own. Edits still pending when the field goes away (a tab
 * switch, a collapsed panel) are saved rather than dropped. */
export function AutosaveField({
  label,
  value,
  onSave,
  multiline = false,
  rows = 4,
  type = 'text',
  placeholder,
  hint,
  disabled,
  hideLabel,
  required,
  size = 'normal',
  ghost,
  compact,
}: Props) {
  const id = useId()
  const [draft, setDraft] = useState(value)
  const [shownValue, setShownValue] = useState(value)
  const [state, setState] = useState<SaveState>('idle')
  const [message, setMessage] = useState('')
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  // The last value sent, so a paste followed by a blur doesn't save twice.
  const sent = useRef<string | null>(null)

  // Adopt a new server value (another save, a refresh) unless we're mid-edit.
  if (value !== shownValue) {
    setShownValue(value)
    if (state !== 'saving') setDraft(value)
  }

  // What's been typed but not yet sent, for the unmount flush below.
  const pending = useRef<string | null>(null)
  const latest = useRef({ onSave, required, value })
  useEffect(() => {
    latest.current = { onSave, required, value }
  })

  useEffect(
    () => () => {
      clearTimeout(timer.current)
      const next = pending.current
      const { onSave: save, required: mustHave, value: saved } = latest.current
      if (next !== null && next !== saved && !(mustHave && !next.trim())) void save(next).catch(() => {})
    },
    [],
  )

  async function commit(next = draft) {
    pending.current = null
    if (next === value || next === sent.current) return
    if (required && !next.trim()) {
      setState('error')
      setMessage('This can’t be empty.')
      setDraft(value)
      return
    }
    setState('saving')
    sent.current = next
    try {
      await onSave(next)
      sent.current = null
      setState('saved')
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setState('idle'), 1800)
    } catch (err) {
      sent.current = null
      setState('error')
      setMessage(err instanceof Error ? err.message : 'Couldn’t save.')
    }
  }

  const common = {
    id,
    value: draft,
    disabled,
    placeholder,
    onChange: (e: { target: { value: string } }) => {
      pending.current = e.target.value
      setDraft(e.target.value)
      if (state === 'error') setState('idle')
    },
    onBlur: () => void commit(),
    // A pasted link is a finished thought: save it now, once the paste has landed.
    onPaste: (e: { currentTarget: { value: string } }) => {
      const field = e.currentTarget
      setTimeout(() => void commit(field.value), 0)
    },
    'aria-describedby': `${id}-status`,
    className: `${styles.control} ${size === 'title' ? styles.title : ''} ${
      size === 'section' ? styles.section : ''
    } ${ghost ? styles.ghost : ''}`,
  }

  return (
    <div className={styles.field}>
      <label htmlFor={id} className={hideLabel ? 'sr-only' : styles.label}>
        {label}
      </label>
      {multiline ? (
        <textarea rows={rows} {...common} />
      ) : (
        <input
          type={type}
          {...common}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void commit(e.currentTarget.value)
          }}
        />
      )}
      <p
        id={`${id}-status`}
        className={`${styles.status} ${compact ? styles.compact : ''} ${
          compact && (state === 'saving' || state === 'saved') ? styles.floating : ''
        }`}
        aria-live="polite"
      >
        {state === 'saving' && 'Saving…'}
        {state === 'saved' && <span className={styles.saved}>Saved</span>}
        {state === 'error' && <span className={styles.error}>{message}</span>}
        {state === 'idle' && !compact && hint}
      </p>
    </div>
  )
}
