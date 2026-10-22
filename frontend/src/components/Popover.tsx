import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'

import styles from './Popover.module.css'

interface Props {
  /** Render the trigger; spread `props` onto the button. */
  trigger: (props: {
    ref: React.RefObject<HTMLButtonElement | null>
    onClick: () => void
    'aria-expanded': boolean
    'aria-controls': string
    'aria-haspopup': 'dialog'
  }, open: boolean) => ReactNode
  children: (close: () => void) => ReactNode
  align?: 'start' | 'end'
  width?: number
  label: string
}

/** A small floating panel anchored to its trigger: closes on Esc, outside
 * click, and returns focus to the trigger. For menus and short lists. */
export function Popover({ trigger, children, align = 'start', width = 280, label }: Props) {
  const [open, setOpen] = useState(false)
  const [up, setUp] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const id = useId()
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)

  // Flip above the trigger when the panel would run off the bottom of the screen.
  useLayoutEffect(() => {
    if (!open) {
      setUp(false)
      return
    }
    const panel = panelRef.current
    const anchor = root.current
    if (!panel || !anchor) return
    const need = panel.getBoundingClientRect().height + 12
    const below = window.innerHeight - anchor.getBoundingClientRect().bottom
    const above = anchor.getBoundingClientRect().top
    setUp(below < need && above > below)
  }, [open])

  useEffect(() => {
    if (!open) return
    function onPointer(e: MouseEvent) {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setOpen(false)
        button.current?.focus()
      }
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className={styles.root} ref={root}>
      {trigger(
        {
          ref: button,
          onClick: () => setOpen((o) => !o),
          'aria-expanded': open,
          'aria-controls': id,
          'aria-haspopup': 'dialog',
        },
        open,
      )}
      {open && (
        <div
          id={id}
          ref={panelRef}
          role="dialog"
          aria-label={label}
          className={`${styles.panel} ${align === 'end' ? styles.end : ''} ${up ? styles.up : ''}`}
          style={{ width }}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}
