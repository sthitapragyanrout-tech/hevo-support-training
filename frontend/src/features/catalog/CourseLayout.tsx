import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Outlet, useLocation, useParams } from 'react-router-dom'

import { Icon } from '../../components/Icon'
import { useMediaQuery } from '../../lib/useMediaQuery'
import { useCourse } from './courseContext'
import { CourseSidebar } from './CourseSidebar'
import styles from './CourseLayout.module.css'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled])'

/** Lesson-route chrome: a persistent sidebar on desktop (no collapse), a
 * focus-managed drawer below 900px. */
export function CourseLayout() {
  const course = useCourse()
  const { nodeId } = useParams()
  const { pathname } = useLocation()
  const isNarrow = useMediaQuery('(max-width: 899px)')
  // Remember *which page* the drawer was opened on, so navigating
  // anywhere closes it without an effect.
  const [openAt, setOpenAt] = useState<string | null>(null)
  const drawerOpen = openAt === pathname
  const setDrawerOpen = (value: boolean) => setOpenAt(value ? pathname : null)
  const opener = useRef<HTMLButtonElement>(null)
  const drawer = useRef<HTMLDivElement>(null)

  const activeLessonId = nodeId ? Number(nodeId) : null
  const open = isNarrow && drawerOpen

  // Move focus into the drawer on open; hand it back on close.
  useEffect(() => {
    if (!open) return
    const trigger = opener.current
    drawer.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    return () => trigger?.focus()
  }, [open])

  function onDrawerKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape') {
      setDrawerOpen(false)
      return
    }
    if (e.key !== 'Tab' || !drawer.current) return
    const items = Array.from(drawer.current.querySelectorAll<HTMLElement>(FOCUSABLE))
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  const sidebar = (
    <CourseSidebar
      course={course}
      activeLessonId={activeLessonId}
      onNavigate={() => setDrawerOpen(false)}
    />
  )

  return (
    <div className={styles.layout}>
      {isNarrow ? (
        <div className={styles.bar}>
          <button
            ref={opener}
            type="button"
            className={styles.contents}
            aria-expanded={open}
            onClick={() => setDrawerOpen(true)}
          >
            <Icon name="menu" size={16} />
            Contents
          </button>
        </div>
      ) : (
        <aside className={styles.sidebar}>{sidebar}</aside>
      )}

      {open && (
        <>
          <div className={styles.backdrop} onClick={() => setDrawerOpen(false)} />
          <div
            ref={drawer}
            className={styles.drawer}
            role="dialog"
            aria-modal="true"
            aria-label="Course contents"
            onKeyDown={onDrawerKeyDown}
          >
            <div className={styles.drawerTop}>
              <button
                type="button"
                className={styles.close}
                aria-label="Close contents"
                onClick={() => setDrawerOpen(false)}
              >
                <Icon name="close" size={16} />
              </button>
            </div>
            {sidebar}
          </div>
        </>
      )}

      <div className={styles.content}>
        <Outlet context={course} />
      </div>
    </div>
  )
}
