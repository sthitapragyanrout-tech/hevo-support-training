import { useRef, useState, type FormEvent } from 'react'

import { Icon } from '../../components/Icon'
import styles from './InlineAdd.module.css'

interface Props {
  /** Button text, e.g. "Add lesson". */
  label: string
  placeholder: string
  onAdd: (title: string) => Promise<void>
  disabled?: boolean
}

/** "+ Add lesson" that turns into a one-line title field in place. Enter
 * adds and stays open for the next one; Esc closes. */
export function InlineAdd({ label, placeholder, onAdd, disabled }: Props) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)

  if (disabled) return null

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!title.trim()) return
    setBusy(true)
    setError(null)
    try {
      await onAdd(title.trim())
      setTitle('')
      input.current?.focus()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Couldn’t add that.')
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button type="button" className={styles.open} onClick={() => setOpen(true)}>
        <Icon name="plus" size={14} /> {label}
      </button>
    )
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      <input
        ref={input}
        className={styles.input}
        value={title}
        placeholder={placeholder}
        aria-label={label}
        autoFocus
        disabled={busy}
        maxLength={255}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setOpen(false)
            setTitle('')
            setError(null)
          }
        }}
      />
      <button type="submit" className={styles.go} disabled={busy || !title.trim()}>
        Add
      </button>
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
    </form>
  )
}
