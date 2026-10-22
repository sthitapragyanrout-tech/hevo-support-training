import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from '../../App'
import { AuthProvider } from '../../lib/auth'
import { mockLearnerApi } from './testApi'

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

const posted = (calls: { method: string; path: string }[], suffix: string, method = 'POST') =>
  calls.filter((c) => c.method === method && c.path.endsWith(suffix))

const row = () => screen.getByText('Sources quiz').closest('li')!
const click = (label: string | RegExp, within_: HTMLElement | Document = document.body) =>
  fireEvent.click(within(within_ as HTMLElement).getByRole('button', { name: label }))

/** Open the sample lesson's quiz once progress has loaded. */
async function startQuiz(label = 'Start quiz') {
  const start = await screen.findByRole('button', { name: label })
  await waitFor(() => expect(start).toBeEnabled())
  fireEvent.click(start)
  await screen.findByText(/Question 1 of 2/)
}

/** Answer both questions (right or wrong) and submit. */
async function take(right: boolean) {
  fireEvent.click(screen.getByLabelText(right ? 'A source' : 'A destination'))
  click('Next')
  await screen.findByText(/Question 2 of 2/)
  if (right) {
    fireEvent.click(screen.getByLabelText('Full load'))
    fireEvent.click(screen.getByLabelText('Incremental'))
  } else {
    fireEvent.click(screen.getByLabelText('Reverse'))
  }
  click('Submit answers')
}

const status = () => screen.findByRole('status')

describe('Quiz, one question at a time', () => {
  it('sits in the activity frame and shows only the current question', async () => {
    mockLearnerApi()
    renderAt('/courses/1/lessons/3')
    await screen.findByText('Sources quiz')
    expect(row()).toHaveTextContent('Quiz · 2 questions · Pass mark 50% · Optional')
    expect(screen.queryByText(/Question 1 of/)).not.toBeInTheDocument()

    await startQuiz()
    expect(screen.getByText('Where does a pipeline read its data from?')).toBeInTheDocument()
    expect(screen.queryByText('Which of these are load modes?')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument()
  })

  it('moves forward only once a question is answered, and Back keeps the answers', async () => {
    mockLearnerApi()
    renderAt('/courses/1/lessons/3')
    await startQuiz()

    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    fireEvent.click(screen.getByLabelText('A source'))
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled()
    click('Next')
    await screen.findByText(/Question 2 of 2/)

    // The last question offers Submit, not Next, and needs an answer.
    expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Submit answers' })).toBeDisabled()
    expect(screen.getByText('Select all that apply.')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Full load'))
    expect(screen.getByRole('button', { name: 'Submit answers' })).toBeEnabled()

    click('Back')
    await screen.findByText(/Question 1 of 2/)
    expect(screen.getByLabelText('A source')).toBeChecked()
    click('Next')
    await screen.findByText(/Question 2 of 2/)
    expect(screen.getByLabelText('Full load')).toBeChecked()
  })

  it('takes one choice for a single answer and several where it says "select all"', async () => {
    mockLearnerApi()
    renderAt('/courses/1/lessons/3')
    await startQuiz()

    const source = screen.getByLabelText('A source')
    const destination = screen.getByLabelText('A destination')
    expect(source).toHaveAttribute('type', 'radio')
    fireEvent.click(source)
    fireEvent.click(destination)
    expect(source).not.toBeChecked()
    expect(destination).toBeChecked()

    click('Next')
    await screen.findByText(/Question 2 of 2/)
    const full = screen.getByLabelText('Full load')
    expect(full).toHaveAttribute('type', 'checkbox')
    fireEvent.click(full)
    fireEvent.click(screen.getByLabelText('Incremental'))
    fireEvent.click(full)
    expect(full).not.toBeChecked()
    expect(screen.getByLabelText('Incremental')).toBeChecked()
  })
})

describe('Results', () => {
  it('a failed attempt shows the percentage, what is needed and the tries left', async () => {
    const { calls } = mockLearnerApi()
    renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(false)

    const result = await status()
    expect(result).toHaveTextContent('Not passed · 0%')
    expect(result).toHaveTextContent('0 of 2 correct.')
    expect(result).toHaveTextContent('You need 1 of 2 to pass. 2 attempts left.')
    expect(posted(calls, '/activities/2/attempts/')).toHaveLength(1)
    expect(row()).toHaveTextContent('Best 0% · 2 attempts left')

    const attempts = screen.getByRole('region', { name: 'Your attempts' })
    expect(within(attempts).getByText('Attempt 1')).toBeInTheDocument()
    expect(within(attempts).getByText('Not passed')).toBeInTheDocument()
  })

  it('keeps the answer key hidden while there are tries left, but lets you review your answers', async () => {
    mockLearnerApi()
    renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(false)
    await status()

    click('Review answers')
    expect(screen.getAllByText('Not quite')).toHaveLength(2)
    expect(screen.queryByText('Correct answer')).not.toBeInTheDocument()
    expect(screen.queryByText(/^Because/)).not.toBeInTheDocument()
    expect(screen.getByLabelText('A destination')).toBeChecked() // what they picked
    click('Hide answers')
    expect(screen.queryByText('Not quite')).not.toBeInTheDocument()
  })

  it('Try again starts over from the first question with nothing selected', async () => {
    mockLearnerApi()
    renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(false)
    await status()
    click('Try again')

    await screen.findByText(/Question 1 of 2/)
    expect(screen.getByLabelText('A destination')).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  })

  it('passing completes the activity and reveals the answers and explanations', async () => {
    mockLearnerApi()
    renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(true)

    const result = await status()
    expect(result).toHaveTextContent('Passed · 100%')
    expect(result).toHaveTextContent('2 of 2 correct. Pass mark 50%.')
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
    expect(row()).toHaveTextContent('Quiz · Passed · best 100% · Optional')

    click('Review answers')
    expect(screen.getAllByText('Correct')).toHaveLength(2)
    expect(screen.getAllByText('Correct answer').length).toBeGreaterThan(0)
    expect(screen.getByText('Because 1.')).toBeInTheDocument()

    click('Close', row())
    expect(within(row()).getByText('Passed')).toBeInTheDocument()
  })

  it('lists every attempt after a second try', async () => {
    mockLearnerApi()
    renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(false)
    await status()
    click('Try again')
    await screen.findByText(/Question 1 of 2/)
    await take(true)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Passed · 100%'))

    const attempts = screen.getByRole('region', { name: 'Your attempts' })
    expect(within(attempts).getAllByRole('listitem')).toHaveLength(2)
    expect(attempts).toHaveTextContent('Attempt 1')
    expect(attempts).toHaveTextContent('0%')
    expect(attempts).toHaveTextContent('Attempt 2')
    expect(attempts).toHaveTextContent('100%')
  })

  it('shows the same scores after a reload, from View results', async () => {
    mockLearnerApi()
    const first = renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(false)
    await status()
    first.unmount()

    renderAt('/courses/1/lessons/3')
    await screen.findByText('Sources quiz')
    await waitFor(() => expect(row()).toHaveTextContent('Best 0% · 2 attempts left'))
    click('View results', row())

    expect(await status()).toHaveTextContent('Not passed · 0%')
    expect(screen.getByRole('region', { name: 'Your attempts' })).toHaveTextContent('Attempt 1')
    click('Review answers')
    expect(screen.getAllByText('Not quite')).toHaveLength(2)
  })
})

describe('Running out of attempts', () => {
  async function useUpOneAttempt(options = {}) {
    const api = mockLearnerApi({ quizMaxAttempts: 1, ...options })
    renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(false)
    await status()
    return api
  }

  it('says the quiz is finished, keeps the best score, and offers no more tries', async () => {
    await useUpOneAttempt()
    expect(screen.getByRole('status')).toHaveTextContent('Not passed · 0%')
    expect(screen.getByRole('status')).toHaveTextContent(
      'You’ve used all your attempts — your best score was 0%. You can continue with the lesson.',
    )
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()

    // The key is revealed once, now that trying again is no longer possible.
    click('Review answers')
    expect(screen.getAllByText('Correct answer').length).toBeGreaterThan(0)

    click('Close', row())
    expect(row()).toHaveTextContent('Not passed · best 0% · all attempts used')
    expect(within(row()).queryByRole('button', { name: /Start quiz|Try again/ })).not.toBeInTheDocument()
    expect(within(row()).getByRole('button', { name: 'View results' })).toBeInTheDocument()
  })

  it('no longer holds the lesson back: a required quiz does not trap the learner', async () => {
    mockLearnerApi({ quizMaxAttempts: 2, quizRequired: true, activities: { 1: 'completed' } })
    renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(false)
    await status()
    // One try left: still required, still blocking.
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeDisabled()
    expect(screen.getByText(/Finish the 1 required activity above first/)).toBeInTheDocument()

    click('Try again')
    await screen.findByText(/Question 1 of 2/)
    await take(false)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Mark complete' })).toBeEnabled())
    expect(screen.queryByText(/Finish the 1 required/)).not.toBeInTheDocument()

    click('Mark complete')
    expect(await screen.findByText('Lesson complete')).toBeInTheDocument()
  })

  it('reopens its scores after a reload even though the quiz is finished', async () => {
    mockLearnerApi({ quizMaxAttempts: 1 })
    const first = renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(false)
    await status()
    first.unmount()

    renderAt('/courses/1/lessons/3')
    await screen.findByText('Sources quiz')
    await waitFor(() => expect(row()).toHaveTextContent('Not passed · best 0% · all attempts used'))
    click('View results', row())
    expect(await status()).toHaveTextContent('Not passed · 0%')
    expect(screen.getByRole('region', { name: 'Your attempts' })).toBeInTheDocument()
  })
})

describe('A required quiz', () => {
  it('holds the lesson open until it is passed, then the lesson can be completed', async () => {
    mockLearnerApi({ quizRequired: true, activities: { 1: 'completed' } })
    renderAt('/courses/1/lessons/3')
    const complete = await screen.findByRole('button', { name: 'Mark complete' })
    await waitFor(() =>
      expect(screen.getByText(/Finish the 1 required activity above first/)).toBeInTheDocument(),
    )
    expect(complete).toBeDisabled()

    await startQuiz()
    await take(true)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Mark complete' })).toBeEnabled())
  })

  it('a failed attempt with tries left does not unlock the lesson', async () => {
    mockLearnerApi({ quizRequired: true, activities: { 1: 'completed' } })
    renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(false)
    await status()
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeDisabled()
  })

  it('is never completed by hand: there is no "mark as read" for a quiz', async () => {
    mockLearnerApi({ quizRequired: true })
    renderAt('/courses/1/lessons/3')
    await screen.findByText('Sources quiz')
    expect(within(row()).queryByRole('button', { name: /I’ve read this|Mark/ })).not.toBeInTheDocument()
  })

  it('shows the server’s reason in place when a submit is refused', async () => {
    mockLearnerApi({
      fail: {
        'POST /api/v1/progress/activities/2/attempts/': {
          status: 409,
          detail: 'You’ve already passed this one.',
        },
      },
    })
    renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(true)
    expect(await screen.findByRole('alert')).toHaveTextContent('You’ve already passed this one.')
    expect(screen.getByRole('button', { name: 'Submit answers' })).toBeEnabled()
  })
})

describe('Reset attempts (testing)', () => {
  it('is not offered unless the server allows it', async () => {
    mockLearnerApi({ quizMaxAttempts: 1 })
    renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(false)
    await status()
    click('Close', row())
    expect(screen.queryByRole('button', { name: 'Reset attempts' })).not.toBeInTheDocument()
  })

  it('wipes the attempts, returns the quiz to a fresh start and re-blocks a required lesson', async () => {
    const { calls } = mockLearnerApi({
      canReset: true,
      quizMaxAttempts: 1,
      quizRequired: true,
      activities: { 1: 'completed' },
    })
    renderAt('/courses/1/lessons/3')
    await startQuiz()
    await take(false)
    await status()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Mark complete' })).toBeEnabled())
    click('Mark complete')
    await screen.findByText('Lesson complete')

    click('Close', row())
    click('Reset attempts', row())

    expect(await within(row()).findByRole('button', { name: 'Start quiz' })).toBeInTheDocument()
    expect(row()).toHaveTextContent('Quiz · 2 questions · Pass mark 50% · Required')
    expect(posted(calls, '/activities/2/attempts/', 'DELETE')).toHaveLength(1)
    await waitFor(() => expect(screen.queryByText('Lesson complete')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeDisabled()
  })
})

describe('Quiz in the author preview', () => {
  it('shows the questions but records and scores nothing', async () => {
    const { calls } = mockLearnerApi({ user: { capabilities: ['catalog.author_content'] } })
    const base = globalThis.fetch as unknown as (u: string, i?: RequestInit) => Promise<Response>
    vi.stubGlobal(
      'fetch',
      vi.fn((u: string, i?: RequestInit) =>
        base(u.replace('/api/v1/authoring/courses/1/preview/', '/api/v1/catalog/courses/1/'), i),
      ),
    )
    renderAt('/studio/courses/1/preview/lessons/3')
    await screen.findByRole('heading', { level: 1, name: 'Pipelines' })

    fireEvent.click(await screen.findByRole('button', { name: 'Start quiz' }))
    await screen.findByText(/Question 1 of 2/)
    fireEvent.click(screen.getByLabelText('A source'))
    click('Next')
    await screen.findByText(/Question 2 of 2/)
    fireEvent.click(screen.getByLabelText('Full load'))
    expect(screen.getByRole('button', { name: 'Submit answers' })).toBeDisabled()
    expect(screen.getByText('Answers aren’t scored in preview.')).toBeInTheDocument()
    expect(calls.some((c) => c.path.includes('/progress/'))).toBe(false)
  })
})
