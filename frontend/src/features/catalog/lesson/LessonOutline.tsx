import { useEffect, useState } from 'react'

import styles from './LessonOutline.module.css'
import type { OutlineItem } from './outline'

/** "In this lesson": a sticky jump list of the lesson's sections. Scroll-spy
 * (by scroll position) marks the section being read. Secondary on purpose — muted, narrow, and
 * hidden below 1280px by the page layout. */
export function LessonOutline({ items, minutes }: { items: OutlineItem[]; minutes: string | null }) {
  const [active, setActive] = useState<string | null>(null)

  useEffect(() => {
    if (items.length === 0) return
    let frame = 0
    // The current section is the last heading that has scrolled past the
    // top of the reading area.
    const update = () => {
      frame = 0
      let current = items[0].id
      for (const item of items) {
        const el = document.getElementById(item.id)
        if (el && el.getBoundingClientRect().top <= 140) current = item.id
      }
      setActive(current)
    }
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update)
    }
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (frame) cancelAnimationFrame(frame)
    }
  }, [items])

  if (items.length < 2) return null

  return (
    <nav className={styles.outline} aria-label="In this lesson">
      <p className={styles.heading}>In this lesson</p>
      <ol className={styles.list}>
        {items.map((item) => (
          <li key={item.id}>
            <a
              href={`#${item.id}`}
              className={`${styles.link} ${active === item.id ? styles.active : ''}`}
              aria-current={active === item.id ? 'location' : undefined}
            >
              {item.text}
            </a>
          </li>
        ))}
      </ol>
      {minutes && <p className={styles.time}>{minutes} total</p>}
    </nav>
  )
}
