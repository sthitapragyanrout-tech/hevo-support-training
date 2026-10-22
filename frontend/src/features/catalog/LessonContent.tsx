import { Children, isValidElement, type ReactElement, type ReactNode } from 'react'
import Markdown from 'react-markdown'

import { Callout } from './lesson/Callout'
import { Flow } from './lesson/Flow'
import { parseFlow } from './lesson/parseFlow'
import { slugify } from './lesson/outline'
import { CALLOUT_KINDS, remarkCallouts, type CalloutKind } from './lesson/remarkCallouts'
import styles from './LessonContent.module.css'

function textOf(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children)
  return ''
}

/** Renders lesson Markdown, plus two authoring extensions:
 *  - `> [!IDEA] / [!WHY] / [!SUPPORT] / [!SCENARIO] / [!PITFALL] / [!TAKEAWAY]`
 *  - ```flow blocks (`A -> B -> C*`)
 * react-markdown ignores raw HTML by default and strips unsafe URLs, so
 * authored content can't inject markup or scripts. */
export function LessonContent({
  markdown,
  lead = true,
}: {
  markdown: string
  /** Style the first paragraph as the lesson's opening hook (intro only —
   * a section's own text is not a second hook). */
  lead?: boolean
}) {
  if (!markdown.trim()) return null
  return (
    <div className={`${styles.prose} ${lead ? styles.lead : ''}`}>
      <Markdown
        remarkPlugins={[remarkCallouts]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
          h2: ({ children }) => <h2 id={slugify(textOf(children))}>{children}</h2>,
          div: (props) => {
            const raw = props as Record<string, unknown>
            const kind = raw['data-callout'] as string | undefined
            if (kind && (CALLOUT_KINDS as readonly string[]).includes(kind)) {
              const title = (raw['data-title'] as string) || undefined
              return (
                <Callout kind={kind as CalloutKind} title={title}>
                  {props.children}
                </Callout>
              )
            }
            return <div>{props.children}</div>
          },
          pre: ({ children }) => {
            const code = Children.toArray(children)[0] as ReactElement<{
              className?: string
              children?: ReactNode
            }> | undefined
            if (code?.props?.className === 'language-flow') {
              const steps = parseFlow(textOf(code.props.children))
              if (steps) return <Flow steps={steps} />
            }
            return <pre>{children}</pre>
          },
        }}
      >
        {markdown}
      </Markdown>
    </div>
  )
}
