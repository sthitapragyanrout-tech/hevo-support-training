import { useEffect, useId, useRef, type ReactNode } from 'react'

import styles from './Dialog.module.css'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

interface Props {
  title: string
  children: ReactNode
  /** Footer buttons (right-aligned). */
  actions: ReactNode
  onClose: () => void
  /** `alert` for destructive confirmations (focus starts on the first button). */
  role?: 'dialog' | 'alertdialog'
  width?: number
}

/** The one modal. Owns the keyboard: focus moves in on open, Tab is trapped,
 * Esc and the backdrop close it, and focus returns to what opened it. */
export function Dialog({ title, children, actions, onClose, role = 'dialog', width = 480 }: Props) {
  const titleId = useId()
  const box = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const el = box.current
    // Keep the page from scrolling behind the modal.
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    if (role === 'alertdialog') el?.querySelector<HTMLElement>('button')?.focus()
    else el?.focus()

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        close.current()
        return
      }
      if (e.key !== 'Tab' || !el) return
      const items = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && (document.activeElement === first || document.activeElement === el)) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
      opener?.focus()
    }
  }, [role])

  return (
    <>
      <div className={styles.backdrop} onClick={onClose} />
      <div
        ref={box}
        tabIndex={-1}
        className={styles.dialog}
        style={{ width: `min(${width}px, calc(100vw - 32px))` }}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        <div className={styles.body}>{children}</div>
        <div className={styles.actions}>{actions}</div>
      </div>
    </>
  )
}
