import type { RatingCriterion } from './adminApi'

/** The overall for a set of scores, the way the server works it out: the mean on the 1–5
 * scale, rounded once, half-up, to two decimals (whole numbers only, so no float surprises).
 * The server decides; this only shows a rater what to expect. */
export function estimate(
  scores: Record<string, number | null>,
  criteria: RatingCriterion[],
  threshold: number,
  minEach: number,
) {
  const values = criteria.map((c) => scores[c.key])
  if (values.some((v) => v == null)) return null
  const marks = values as number[]
  const n = marks.length
  const hundredths = Math.floor((marks.reduce((a, b) => a + b, 0) * 200 + n) / (2 * n))
  const below = minEach ? criteria.filter((c) => (scores[c.key] as number) < minEach).map((c) => c.label) : []
  return { raw: hundredths / 100, passes: hundredths >= Math.round(threshold * 500) && below.length === 0, below }
}
