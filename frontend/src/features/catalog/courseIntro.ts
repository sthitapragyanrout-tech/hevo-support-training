export interface CourseIntro {
  /** Markdown before the "What you'll learn" section: what the course is
   * and why it matters. */
  lead: string[]
  outcomes: string[]
}

/** The course root's `description` is Markdown: lead paragraph(s), then an
 * optional `## What you'll learn` bullet list. No schema needed. */
export function parseCourseIntro(markdown: string): CourseIntro {
  const lines = markdown.split('\n')
  const headingAt = lines.findIndex((l) => /^##\s+what you.?ll learn\s*$/i.test(l.trim()))
  const leadText = (headingAt === -1 ? lines : lines.slice(0, headingAt)).join('\n')
  const outcomes =
    headingAt === -1
      ? []
      : lines
          .slice(headingAt + 1)
          .map((l) => /^\s*[-*]\s+(.+?)\s*$/.exec(l)?.[1])
          .filter((t): t is string => Boolean(t))
  return {
    lead: leadText
      .split(/\n\s*\n/)
      .map((p) => p.trim())
      .filter(Boolean),
    outcomes,
  }
}

/** Inverse of `parseCourseIntro`: the Markdown stored in the course root. */
export function composeCourseIntro(lead: string[], outcomes: string[]): string {
  const parts = [lead.map((p) => p.trim()).filter(Boolean).join('\n\n')]
  const items = outcomes.map((o) => o.trim()).filter(Boolean)
  if (items.length > 0) {
    parts.push(`## What you’ll learn\n\n${items.map((o) => `- ${o}`).join('\n')}`)
  }
  return parts.filter(Boolean).join('\n\n')
}
