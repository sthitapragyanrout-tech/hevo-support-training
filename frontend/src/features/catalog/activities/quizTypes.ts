export interface Question {
  text: string
  choices: string[]
  multiple: boolean
}

/** The learner payload carries questions and choices only — never the key. */
export function parseQuestions(config: Record<string, unknown>): Question[] {
  const raw = Array.isArray(config.questions) ? config.questions : []
  return raw.map((q: Partial<Question>) => ({
    text: typeof q.text === 'string' ? q.text : '',
    choices: Array.isArray(q.choices) ? q.choices.map(String) : [],
    multiple: q.multiple === true,
  }))
}

export const percent = (score: number) => `${Math.round(score * 100)}%`

export const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
