export interface OutlineItem {
  id: string
  text: string
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
}

/** The lesson's `##` sections, in order — skipping anything inside code
 * fences. Ids match what `LessonContent` puts on the rendered headings. */
export function extractOutline(markdown: string): OutlineItem[] {
  const items: OutlineItem[] = []
  let inFence = false
  for (const line of markdown.split('\n')) {
    if (line.trimStart().startsWith('```')) inFence = !inFence
    if (inFence) continue
    const match = /^##\s+(.+?)\s*$/.exec(line)
    if (match) {
      const text = match[1].replace(/[*_`]/g, '')
      items.push({ id: slugify(text), text })
    }
  }
  return items
}
