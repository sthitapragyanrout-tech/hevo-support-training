import { useEffect, useId, useRef, useState } from 'react'

import { Icon, type IconName } from '../../components/Icon'
import { Popover } from '../../components/Popover'
import { LessonContent } from '../catalog/LessonContent'
import styles from './MarkdownEditor.module.css'

interface Snippet {
  label: string
  text: string
  hint: string
  icon: IconName
}

const SNIPPETS: Snippet[] = [
  { label: 'Key idea', text: '> [!IDEA]\n> ', hint: 'The one thing to hold onto', icon: 'bulb' },
  { label: 'Why it matters', text: '> [!WHY]\n> ', hint: 'Why a CX engineer should care', icon: 'target' },
  { label: 'Support lens', text: '> [!SUPPORT]\n> ', hint: 'How to think about it on a ticket', icon: 'search' },
  {
    label: 'Customer scenario',
    text: '> [!SCENARIO] A short title\n> > “What the customer says.”\n>\n> **Recognise:** \n>\n> **Investigate:** \n>\n> **Don’t assume:** \n>\n> **Communicate:** ',
    hint: 'A realistic ticket, then how to think',
    icon: 'chat',
  },
  { label: 'Pitfall', text: '> [!PITFALL]\n> ', hint: 'A common mistake', icon: 'alert' },
  { label: 'Takeaway', text: '> [!TAKEAWAY]\n> - ', hint: 'Two to four things to remember', icon: 'bookmark' },
  {
    label: 'Diagram',
    text: '```flow\nStep one -> Step two* -> Step three\n```',
    hint: 'A flow; * highlights a step',
    icon: 'arrowRight',
  },
]

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

interface Props {
  label: string
  value: string
  onSave: (value: string) => Promise<void>
  hint?: string
  disabled?: boolean
  rows?: number
}

/** Markdown on a writing surface: proportional type, grows as you write, the
 * lesson patterns in one menu, and a preview that is the real learner
 * renderer. Saves when focus leaves the box. */
export function MarkdownEditor({ label, value, onSave, hint, disabled, rows = 5 }: Props) {
  const id = useId()
  const area = useRef<HTMLTextAreaElement>(null)
  const [draft, setDraft] = useState(value)
  const [shown, setShown] = useState(value)
  const [mode, setMode] = useState<'write' | 'preview'>('write')
  const [state, setState] = useState<SaveState>('idle')
  const [message, setMessage] = useState('')

  if (value !== shown) {
    setShown(value)
    if (state !== 'saving') setDraft(value)
  }

  // Grow with the text instead of scrolling inside a small box.
  useEffect(() => {
    const el = area.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight + 2}px`
  }, [draft, mode])

  async function commit(next = draft) {
    if (next === value) return
    setState('saving')
    try {
      await onSave(next)
      setState('saved')
      setTimeout(() => setState((s) => (s === 'saved' ? 'idle' : s)), 1800)
    } catch (err) {
      setState('error')
      setMessage(err instanceof Error ? err.message : 'Couldn’t save.')
    }
  }

  function insert(text: string) {
    const el = area.current
    if (!el) return
    const start = el.selectionStart
    const end = el.selectionEnd
    const before = draft.slice(0, start)
    const after = draft.slice(end)
    const lead = before && !before.endsWith('\n\n') ? (before.endsWith('\n') ? '\n' : '\n\n') : ''
    const trail = after && !after.startsWith('\n') ? '\n\n' : ''
    setDraft(`${before}${lead}${text}${trail}${after}`)
    const caret = before.length + lead.length + text.length
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(caret, caret)
    })
  }

  return (
    <div className={styles.editor}>
      <div className={styles.head}>
        <label htmlFor={id} className={styles.label}>
          {label}
        </label>
        <div className={styles.tools}>
          {!disabled && mode === 'write' && (
            <Popover
              label="Insert a learning pattern"
              align="end"
              width={300}
              trigger={(props) => (
                <button type="button" className={`btn btn-ghost btn-sm ${styles.insert}`} {...props}>
                  <Icon name="plus" size={14} /> Insert
                </button>
              )}
            >
              {(close) => (
                <ul className={styles.menu} role="menu" aria-label="Insert a learning pattern">
                  {SNIPPETS.map((s) => (
                    <li key={s.label} role="none">
                      <button
                        type="button"
                        role="menuitem"
                        className={styles.item}
                        onClick={() => {
                          close()
                          insert(s.text)
                        }}
                      >
                        <Icon name={s.icon} size={16} />
                        <span>
                          <strong>{s.label}</strong>
                          <span className={styles.itemHint}>{s.hint}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Popover>
          )}
          <div className={styles.modes} role="tablist" aria-label={`${label} view`}>
            {(['write', 'preview'] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                className={`${styles.mode} ${mode === m ? styles.on : ''}`}
                onClick={() => {
                  if (m === 'preview') void commit()
                  setMode(m)
                }}
              >
                {m === 'write' ? 'Write' : 'Preview'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {mode === 'write' ? (
        <textarea
          id={id}
          ref={area}
          className={styles.area}
          rows={rows}
          value={draft}
          disabled={disabled}
          spellCheck
          placeholder={disabled ? undefined : 'Write in Markdown. Use Insert for callouts and diagrams.'}
          onChange={(e) => {
            setDraft(e.target.value)
            if (state === 'error') setState('idle')
          }}
          onBlur={() => void commit()}
          aria-describedby={`${id}-status`}
        />
      ) : (
        <div className={styles.preview}>
          {draft.trim() ? (
            <LessonContent markdown={draft} lead={false} />
          ) : (
            <p className={styles.empty}>Nothing to preview yet.</p>
          )}
        </div>
      )}

      <p id={`${id}-status`} className={styles.status} aria-live="polite">
        {state === 'saving' && 'Saving…'}
        {state === 'saved' && <span className={styles.saved}>Saved</span>}
        {state === 'error' && <span className={styles.error}>{message}</span>}
        {state === 'idle' && !disabled && hint}
      </p>
    </div>
  )
}
