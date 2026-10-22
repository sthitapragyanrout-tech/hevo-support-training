export const CALLOUT_KINDS = ['idea', 'why', 'support', 'scenario', 'pitfall', 'takeaway'] as const
export type CalloutKind = (typeof CALLOUT_KINDS)[number]

// Loose mdast shape — enough for this transform without pulling in type deps.
interface MdNode {
  type: string
  value?: string
  children?: MdNode[]
  data?: { hName?: string; hProperties?: Record<string, unknown> }
}

const MARKER = /^\[!(IDEA|WHY|SUPPORT|SCENARIO|PITFALL|TAKEAWAY)\][ \t]*(.*)$/i

/** Turns `> [!KIND] Optional title` blockquotes into tagged <div>s that the
 * `Callout` component renders. A plain `>` blockquote is left alone. */
export function remarkCallouts() {
  return (tree: MdNode) => visit(tree)
}

function visit(node: MdNode) {
  if (node.type === 'blockquote') tag(node)
  node.children?.forEach(visit)
}

function tag(blockquote: MdNode) {
  const firstParagraph = blockquote.children?.[0]
  const firstText = firstParagraph?.type === 'paragraph' ? firstParagraph.children?.[0] : undefined
  if (!firstParagraph || firstText?.type !== 'text' || firstText.value === undefined) return

  // The marker is the first line of the first text node; the rest of that
  // line (if any) is the callout's title.
  const [firstLine, ...rest] = firstText.value.split('\n')
  const match = MARKER.exec(firstLine)
  if (!match) return

  const title = match[2].trim()
  if (rest.length > 0) {
    firstText.value = rest.join('\n')
  } else {
    firstParagraph.children!.shift() // marker-only line: drop the empty text node
    if (firstParagraph.children!.length === 0) blockquote.children!.shift()
  }

  blockquote.data = {
    hName: 'div',
    hProperties: { 'data-callout': match[1].toLowerCase(), 'data-title': title },
  }
}
