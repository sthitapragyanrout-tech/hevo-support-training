import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ManualSimEditor } from './ManualSimEditor'
import type { AuthActivity } from './types'

const CRITERIA = [
  { key: 'c1', label: 'Diagnosis', description: 'Found the cause', guidance: 'RATER NOTE one' },
  { key: 'c2', label: 'Tone', description: 'Kind and clear', guidance: 'RATER NOTE two' },
]

function activity(config: Record<string, unknown> = {}): AuthActivity {
  return {
    id: 31,
    activity_type: 'manual_sim',
    title: 'Customer reply',
    config,
    is_required: true,
    points: 0,
    max_attempts: 0,
    mastery_threshold: null,
    order: 0,
    needs_setup: false,
    completable: true,
  }
}

function mount(config: Record<string, unknown> = {}, disabled = false) {
  const save = vi.fn(async () => {})
  const view = render(<ManualSimEditor activity={activity(config)} disabled={disabled} save={save} />)
  return { save, view }
}

const lastConfig = (save: ReturnType<typeof vi.fn>) =>
  (save.mock.calls[save.mock.calls.length - 1] as [{ config: Record<string, unknown> }])[0].config

function edit(label: string | RegExp, value: string) {
  const field = screen.getByLabelText(label)
  fireEvent.change(field, { target: { value } })
  fireEvent.blur(field)
}

describe('Mentor-rated simulation editor', () => {
  it('shows what is saved, with the pass mark out of 5 and no percentages', () => {
    mount({ scenario: 'A pipeline stopped.', criteria: CRITERIA, pass_threshold: 0.7, min_each: 2, due_days: 5, revision_days: 2, review_hours: 24 })
    expect(screen.getByLabelText('Scenario')).toHaveValue('A pipeline stopped.')
    expect(screen.getByLabelText('Pass mark (out of 5)')).toHaveValue(3.5)
    expect(screen.getByLabelText('Lowest score on any criterion')).toHaveValue(2)
    expect(screen.getByLabelText('Days to hand in')).toHaveValue(5)
    expect(screen.getByLabelText('Days to revise')).toHaveValue(2)
    expect(screen.getByLabelText('Mentor review target (hours)')).toHaveValue(24)
    expect(screen.getAllByLabelText(/^Criterion \d$/)).toHaveLength(2)
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })

  it('uses the defaults the server uses when nothing is set', () => {
    mount({})
    expect(screen.getByLabelText('Pass mark (out of 5)')).toHaveValue(3.5)
    expect(screen.getByLabelText('Days to hand in')).toHaveValue(7)
    expect(screen.getByLabelText('Days to revise')).toHaveValue(3)
    expect(screen.getByLabelText('Mentor review target (hours)')).toHaveValue(0)
    expect(screen.getByLabelText(/Learners may attach/)).toBeChecked()
    expect(screen.getByText(/can’t be published without one/)).toBeInTheDocument()
  })

  it('keeps the raters’ guidance in its own field, labelled as raters-only', () => {
    mount({ criteria: CRITERIA })
    expect(screen.getAllByLabelText('Guidance for raters')[0]).toHaveValue('RATER NOTE one')
    expect(screen.getByText(/only ever shown to raters/)).toBeInTheDocument()
  })

  it('converts the pass mark back to a 0–1 threshold when saving', async () => {
    const { save } = mount({ scenario: 'x' })
    edit('Pass mark (out of 5)', '4')
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastConfig(save)).toMatchObject({ scenario: 'x', pass_threshold: 0.8 })
  })

  it.each([['0'], ['5.5'], ['']])('refuses a pass mark of “%s”', async (value) => {
    const { save } = mount({})
    edit('Pass mark (out of 5)', value)
    expect(await screen.findByText('Enter a pass mark from 1 to 5 (out of 5).')).toBeInTheDocument()
    expect(save).not.toHaveBeenCalled()
  })

  it.each([['1.5'], ['6'], ['-1']])('refuses a minimum score of “%s”', async (value) => {
    const { save } = mount({})
    edit('Lowest score on any criterion', value)
    expect(await screen.findByText(/from 0 to 5 \(0 means no minimum\)/)).toBeInTheDocument()
    expect(save).not.toHaveBeenCalled()
  })

  it('saves deadlines and the review target as whole numbers, and refuses nonsense', async () => {
    const { save } = mount({})
    edit('Days to hand in', '0')
    await waitFor(() => expect(lastConfig(save)).toMatchObject({ due_days: 0 }))
    edit('Days to revise', '2.5')
    expect(await screen.findByText(/Enter a whole number from 0 to 365/)).toBeInTheDocument()
    edit('Mentor review target (hours)', '36')
    await waitFor(() => expect(lastConfig(save)).toMatchObject({ review_hours: 36 }))
  })

  it('adds a criterion with its own key, and stops at eight', async () => {
    const { save, view } = mount({ criteria: CRITERIA })
    fireEvent.click(screen.getByRole('button', { name: 'Add a criterion' }))
    await waitFor(() => expect(save).toHaveBeenCalled())
    const added = (lastConfig(save).criteria as { key: string; label: string }[])[2]
    expect(added.key).toBe('c3')
    const eight = Array.from({ length: 8 }, (_, i) => ({ key: `c${i + 1}`, label: `L${i + 1}`, description: '', guidance: '' }))
    view.rerender(<ManualSimEditor activity={activity({ criteria: eight })} disabled={false} save={save} />)
    expect(screen.getByRole('button', { name: 'Add a criterion' })).toBeDisabled()
    expect(screen.getByText(/At most 8/)).toBeInTheDocument()
  })

  it('removes and reorders criteria', async () => {
    const { save } = mount({ criteria: CRITERIA })
    fireEvent.click(screen.getAllByRole('button', { name: 'Move down' })[0])
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect((lastConfig(save).criteria as { key: string }[]).map((c) => c.key)).toEqual(['c2', 'c1'])
    fireEvent.click(screen.getByRole('button', { name: 'Remove criterion 2' }))
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2))
    expect((lastConfig(save).criteria as { key: string }[]).length).toBe(1)
  })

  it('does not lose an edit when two fields are changed in quick succession', async () => {
    // The Module 4 trap: every save sends the whole config, so a second edit made before the
    // first returns must not be built from the stale copy.
    let release: () => void = () => {}
    const save = vi.fn(
      (changes: { config?: Record<string, unknown> }) =>
        new Promise<void>((resolve) => {
          if (save.mock.calls.length === 1) release = resolve
          else resolve()
          void changes
        }),
    )
    render(<ManualSimEditor activity={activity({ scenario: 'old' })} disabled={false} save={save} />)
    edit('Scenario', 'New scenario')
    edit('Days to hand in', '4')
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1)) // the second waits its turn
    release()
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2))
    expect(lastConfig(save as unknown as ReturnType<typeof vi.fn>)).toMatchObject({ scenario: 'New scenario', due_days: 4 })
  })

  it('toggles attachments and writes the whole config', async () => {
    const { save } = mount({ scenario: 'x', criteria: CRITERIA })
    fireEvent.click(screen.getByLabelText(/Learners may attach/))
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastConfig(save)).toMatchObject({ allow_files: false, scenario: 'x' })
    expect((lastConfig(save).criteria as unknown[]).length).toBe(2)
  })

  it('offers what holds the next lesson, defaulting to handing in', async () => {
    const { save } = mount({ scenario: 'x', criteria: CRITERIA })
    expect(screen.getByLabelText(/^Handing in the work/)).toBeChecked()
    expect(screen.getByLabelText(/^Passing the rating/)).not.toBeChecked()
    fireEvent.click(screen.getByLabelText(/^Passing the rating/))
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastConfig(save)).toMatchObject({ holds_next: 'pass', scenario: 'x' })
  })

  it('shows a saved “pass” setting', () => {
    mount({ scenario: 'x', criteria: CRITERIA, holds_next: 'pass' })
    expect(screen.getByLabelText(/^Passing the rating/)).toBeChecked()
  })

  it('locks every control when the course can’t be edited', () => {
    mount({ criteria: CRITERIA }, true)
    for (const label of ['Scenario', 'Pass mark (out of 5)', 'Days to hand in', 'Days to revise', 'Mentor review target (hours)']) {
      expect(screen.getByLabelText(label)).toBeDisabled()
    }
    expect(screen.getByRole('button', { name: 'Add a criterion' })).toBeDisabled()
    expect(screen.getByLabelText(/Learners may attach/)).toBeDisabled()
    expect(screen.getByLabelText(/^Handing in the work/)).toBeDisabled()
  })
})
