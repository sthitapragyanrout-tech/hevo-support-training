import { describe, expect, it } from 'vitest'

import {
  addChoice,
  correctChoices,
  moveItemSafe,
  newQuestion,
  removeChoice,
  setCorrect,
  setMultiple,
  type QuizQuestion,
} from './quizModel'

const single: QuizQuestion = { text: 'Q', choices: ['a', 'b', 'c'], answer: 1 }
const multi: QuizQuestion = { text: 'Q', choices: ['a', 'b', 'c'], answer: [0, 2] }

describe('quiz question edits', () => {
  it('a new question has two empty choices and no answer picked yet', () => {
    expect(newQuestion()).toEqual({ text: '', choices: ['', ''] })
    expect(correctChoices(newQuestion())).toEqual([])
  })

  it('picking a correct choice replaces it for a single answer and adds for several', () => {
    expect(setCorrect(single, 2, true).answer).toBe(2)
    expect(setCorrect(multi, 1, true).answer).toEqual([0, 1, 2])
    expect(setCorrect(multi, 0, false).answer).toEqual([2])
    expect(setCorrect(multi, 2, false).answer).toEqual([0])
  })

  it('switching to several keeps the answer; switching back keeps the first', () => {
    expect(setMultiple(single, true).answer).toEqual([1])
    expect(setMultiple(multi, false).answer).toBe(0)
    expect(setMultiple(single, false)).toBe(single)
    expect('answer' in setMultiple({ ...multi, answer: [] }, false)).toBe(false)
  })

  it('removing a choice keeps the answers pointing at the same choices', () => {
    expect(removeChoice(single, 0)).toEqual({ text: 'Q', choices: ['b', 'c'], answer: 0 })
    expect(removeChoice(single, 2).answer).toBe(1)
    expect('answer' in removeChoice(single, 1)).toBe(false) // the correct one went
    expect(removeChoice(multi, 1)).toEqual({ text: 'Q', choices: ['a', 'c'], answer: [0, 1] })
    expect(removeChoice(multi, 0).answer).toEqual([1])
  })

  it('adds an empty choice at the end', () => {
    expect(addChoice(single).choices).toEqual(['a', 'b', 'c', ''])
  })

  it('moves an item and ignores moves off either end', () => {
    expect(moveItemSafe([1, 2, 3], 2, 0)).toEqual([3, 1, 2])
    const same = [1, 2]
    expect(moveItemSafe(same, 0, -1)).toBe(same)
    expect(moveItemSafe(same, 1, 2)).toBe(same)
  })
})
