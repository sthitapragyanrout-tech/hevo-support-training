/** A score out of 5: "3.5 / 5", "3.84 / 5" — never padded, never a percentage. */
export const outOf5 = (n: number) => `${Number(n.toFixed(2))} / 5`
