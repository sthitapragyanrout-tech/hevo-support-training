import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BotSimEditor } from './BotSimEditor'
import type { AuthActivity } from './types'

const OPTIONS = {
  topics: [
    { key: 'billing', label: 'billing — how events are counted' },
    { key: 'alerts', label: 'alert and notification settings — Slack' },
  ],
  personas: ['urgent', 'technical', 'non-technical', 'terse'],
  model_ready: true,
  counts: { approved: 3, draft: 0, retired: 0 },
}

function activity(config: Record<string, unknown> = {}, over: Partial<AuthActivity> = {}): AuthActivity {
  return {
    id: 21,
    activity_type: 'bot_sim',
    title: 'Practice ticket',
    config,
    is_required: true,
    points: 0,
    max_attempts: 0,
    mastery_threshold: null,
    order: 0,
    needs_setup: false,
    completable: true,
    ...over,
  }
}

let count: number
let counts: { persona: string | null; topics: string | null }[]

beforeEach(() => {
  count = 8
  counts = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const [path, search = ''] = url.split('?')
      let body: unknown = { detail: 'Not found.' }
      let status = 404
      if (path === '/api/v1/admin/practice/options/') [status, body] = [200, OPTIONS]
      if (path === '/api/v1/sim/scenario-count/') {
        const q = new URLSearchParams(search)
        counts.push({ persona: q.get('persona'), topics: q.get('topics') })
        ;[status, body] = [200, { count }]
      }
      return { ok: status < 300, status, statusText: 'x', json: async () => body }
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function mount(config: Record<string, unknown> = {}, over: Partial<AuthActivity> = {}, disabled = false) {
  const save = vi.fn(async () => {})
  const view = render(
    <MemoryRouter>
      <BotSimEditor activity={activity(config, over)} disabled={disabled} save={save} />
    </MemoryRouter>,
  )
  return { save, view }
}

const lastConfig = (save: ReturnType<typeof vi.fn>) =>
  (save.mock.calls[save.mock.calls.length - 1] as [{ config: Record<string, unknown> }])[0].config

function edit(label: string, value: string) {
  const field = screen.getByLabelText(label)
  fireEvent.change(field, { target: { value } })
  fireEvent.blur(field)
}

describe('Practice ticket editor', () => {
  it('shows the saved settings, with the pass mark out of 5 rather than as a percent', async () => {
    mount({ persona: 'urgent', pass_threshold: 0.7, max_exchanges: 5 })
    expect(screen.getByLabelText('Customer type')).toHaveValue('urgent')
    expect(screen.getByLabelText('Pass mark (out of 5)')).toHaveValue(3.5)
    expect(screen.getByLabelText('Replies allowed')).toHaveValue(5)
    expect(screen.getByLabelText('Tickets to complete')).toHaveValue(5)
    expect(screen.getByLabelText('Most tickets allowed')).toHaveValue(0)
    expect(await screen.findByLabelText('billing')).not.toBeChecked()
  })

  it('uses the same defaults a learner’s ticket does when nothing is set', () => {
    mount({})
    expect(screen.getByLabelText('Customer type')).toHaveValue('random')
    expect(screen.getByLabelText('Pass mark (out of 5)')).toHaveValue(3.5)
    expect(screen.getByLabelText('Replies allowed')).toHaveValue(6)
    // five finished tickets, and no passing average needed — it's practice, not a test
    expect(screen.getByLabelText('Tickets to complete')).toHaveValue(5)
    expect(screen.getByLabelText(/Also require the average of the last 5/)).not.toBeChecked()
    expect(screen.getByText(/finishing 5 tickets completes it whatever they scored/)).toBeInTheDocument()
  })

  it('converts the pass mark back to a 0–1 threshold when saving', async () => {
    const { save } = mount({ persona: 'random' })
    edit('Pass mark (out of 5)', '4')
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastConfig(save)).toMatchObject({ persona: 'random', pass_threshold: 0.8 })
  })

  it.each([['1.5'], ['5.5'], ['']])('refuses a pass mark of “%s”', async (text) => {
    const { save } = mount({})
    edit('Pass mark (out of 5)', text)
    expect(await screen.findByText('Enter a pass mark from 2 to 5 (out of 5).')).toBeInTheDocument()
    expect(save).not.toHaveBeenCalled()
  })

  it('keeps replies between 3 and 6', async () => {
    const { save } = mount({})
    edit('Replies allowed', '7')
    expect(await screen.findByText('Enter a whole number from 3 to 6.')).toBeInTheDocument()
    expect(save).not.toHaveBeenCalled()
    edit('Replies allowed', '4')
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastConfig(save)).toMatchObject({ max_exchanges: 4 })
  })

  it('saves the number of tickets to complete, within 1 to 20', async () => {
    const { save } = mount({})
    edit('Tickets to complete', '3')
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastConfig(save)).toMatchObject({ required_tickets: 3 })
    for (const bad of ['0', '21', '2.5', 'x']) {
      edit('Tickets to complete', bad)
      expect(await screen.findByText('Enter a whole number from 1 to 20.')).toBeInTheDocument()
    }
    expect(save).toHaveBeenCalledTimes(1)
  })

  it('will not ask for more tickets than the limit allows', async () => {
    const { save } = mount({}, { max_attempts: 3 })
    edit('Tickets to complete', '4')
    expect(await screen.findByText(/at most 3 tickets, so they couldn’t finish 4/)).toBeInTheDocument()
    expect(save).not.toHaveBeenCalled()
  })

  it('saves the most tickets allowed on the activity itself, and 0 means no limit', async () => {
    const { save } = mount({})
    edit('Most tickets allowed', '8')
    await waitFor(() => expect(save).toHaveBeenCalledWith({ max_attempts: 8 }))
    edit('Most tickets allowed', '-1')
    expect(await screen.findByText('Enter a whole number, or 0 for no limit.')).toBeInTheDocument()
  })

  it('will not set a limit below the tickets to complete', async () => {
    const { save } = mount({ required_tickets: 5 })
    edit('Most tickets allowed', '3')
    expect(await screen.findByText(/must finish 5 tickets, so the limit can’t be lower than that/)).toBeInTheDocument()
    expect(save).not.toHaveBeenCalled()
  })

  it('can also require the average to reach the pass mark', async () => {
    const { save } = mount({ required_tickets: 4 })
    fireEvent.click(screen.getByLabelText(/Also require the average of the last 4/))
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastConfig(save)).toMatchObject({ require_average: true, required_tickets: 4 })
  })

  it('picks the customer type and the topics', async () => {
    const { save } = mount({ persona: 'random', topics: ['billing'] })
    fireEvent.change(screen.getByLabelText('Customer type'), { target: { value: 'terse' } })
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastConfig(save)).toMatchObject({ persona: 'terse', topics: ['billing'] })

    fireEvent.click(await screen.findByLabelText('alert and notification settings'))
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2))
    expect(lastConfig(save).topics).toEqual(['billing', 'alerts'])
  })

  it('unticking the last topic means any topic', async () => {
    const { save } = mount({ topics: ['billing'] })
    const box = await screen.findByLabelText('billing')
    expect(box).toBeChecked()
    fireEvent.click(box)
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(lastConfig(save).topics).toEqual([])
  })
})

describe('Practice ticket editor — scenario availability', () => {
  it('says how many approved scenarios match, and asks with the current filter', async () => {
    mount({ persona: 'urgent', topics: ['billing', 'alerts'] })
    expect(await screen.findByRole('status')).toHaveTextContent('8 approved scenarios match these settings.')
    expect(counts[0]).toEqual({ persona: 'urgent', topics: 'billing,alerts' })
    expect(screen.getByRole('link', { name: 'Practice scenarios' })).toHaveAttribute('href', '/admin/practice')
    expect(screen.getByRole('status')).toHaveTextContent('nothing is scored')
  })

  it('uses the singular for one when one is enough', async () => {
    count = 1
    mount({ required_tickets: 1 })
    expect(await screen.findByRole('status')).toHaveTextContent('1 approved scenario match these settings.')
  })

  it('says it can’t be published when none match', async () => {
    count = 0
    mount({})
    expect(await screen.findByRole('alert')).toHaveTextContent('No approved scenarios match these settings, so this can’t be published yet.')
  })

  it('can’t be published with fewer scenarios than tickets to finish', async () => {
    count = 3
    mount({})
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Only 3 approved scenarios match, but learners must finish 5 — this can’t be published yet.',
    )
  })

  it('warns when someone who skips a lot could run out', async () => {
    count = 7 // enough to finish 5, not enough if they skip up to 5
    mount({})
    expect(await screen.findByRole('status')).toHaveTextContent('could run out of new questions')
  })

  it('is quiet when there are plenty', async () => {
    count = 12
    mount({})
    expect(await screen.findByRole('status')).not.toHaveTextContent('run out')
  })

  it('asks again when the saved filter changes, and shows the new answer', async () => {
    const { save, view } = mount({ persona: 'random' })
    expect(await screen.findByRole('status')).toHaveTextContent('8 approved')
    count = 0
    // The Studio re-renders the editor with the saved config after a save.
    view.rerender(
      <MemoryRouter>
        <BotSimEditor activity={activity({ persona: 'technical' })} disabled={false} save={save} />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('No approved scenarios match')
    expect(counts.map((c) => c.persona)).toEqual(['random', 'technical'])
  })

  it('does not break when the count cannot be fetched', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, statusText: 'x', json: async () => ({}) })))
    mount({})
    expect(await screen.findByRole('status')).toHaveTextContent('Checking available scenarios…')
  })
})

describe('Practice ticket editor — read-only', () => {
  it('locks every control while the course can’t be edited', async () => {
    mount({ topics: ['billing'] }, {}, true)
    expect(screen.getByLabelText('Customer type')).toBeDisabled()
    expect(screen.getByLabelText('Pass mark (out of 5)')).toBeDisabled()
    expect(screen.getByLabelText('Replies allowed')).toBeDisabled()
    expect(screen.getByLabelText('Most tickets allowed')).toBeDisabled()
    expect(screen.getByLabelText('Tickets to complete')).toBeDisabled()
    expect(screen.getByLabelText(/Also require the average/)).toBeDisabled()
    expect(await screen.findByLabelText('billing')).toBeDisabled()
  })
})
