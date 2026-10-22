export interface FlowStep {
  label: string
  highlight: boolean
}

/** `A -> B -> C*` (a trailing `*` highlights the step the lesson is about).
 * Returns null when the block isn't a usable chain, so the caller can fall
 * back to a plain code block. */
export function parseFlow(source: string): FlowStep[] | null {
  const steps = source
    .trim()
    .split('->')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => ({
      label: s.replace(/\*+$/, '').trim(),
      highlight: s.endsWith('*'),
    }))
  return steps.length >= 2 && steps.every((s) => s.label) ? steps : null
}
