import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { render } from '@testing-library/react'

import { mockApi, renderAt, type Call } from '../admin/testHelpers'
import { timeAgo } from './format'
import { NotificationsProvider, POLL_MS, useNotificationCount } from './NotificationsContext'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
})

const note = (id: number, over: Partial<Record<string, unknown>> = {}) => ({
  id,
  kind: 'enrolled',
  title: `Notice ${id}`,
  body: 'Something happened.',
  link: `/courses/${id}`,
  created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
  read: false,
  ...over,
})

const LIST = '/api/v1/notifications/'
const COUNT = '/api/v1/notifications/unread-count/'

/** A fake notifications service that remembers what is read. */
function serve(initial: ReturnType<typeof note>[], extra: Record<string, unknown> = {}, user = {}) {
  const items = initial.map((n) => ({ ...n }))
  const unread = () => items.filter((n) => !n.read).length
  const calls = mockApi(
    [],
    {
      [`GET ${COUNT}`]: () => ({ body: { unread_count: unread() } }),
      [`GET ${LIST}`]: (c: Call) => {
        const page = Number(c.query.get('page') ?? 1)
        const size = Number(c.query.get('page_size') ?? 20)
        const slice = items.slice((page - 1) * size, page * size)
        return {
          body: {
            results: slice,
            count: items.length,
            page,
            pages: Math.max(1, Math.ceil(items.length / size)),
            unread_count: unread(),
          },
        }
      },
      [`POST ${LIST}read-all/`]: () => {
        items.forEach((n) => (n.read = true))
        return { body: { unread_count: 0 } }
      },
      ...extra,
    },
    user,
  )
  // One handler for "POST /notifications/<id>/read/": the helper matches exact paths, so add them.
  return { calls, items, unread }
}

function serveReads(items: ReturnType<typeof note>[]) {
  const routes: Record<string, unknown> = {}
  for (const n of items) {
    routes[`POST ${LIST}${n.id}/read/`] = () => {
      n.read = true
      return { body: { ...n, unread_count: items.filter((x) => !x.read).length } }
    }
  }
  return routes
}

const bell = () => screen.findByRole('button', { name: /^Notifications/ })

describe('the bell', () => {
  it('shows no number when nothing is unread', async () => {
    serve([note(1, { read: true })])
    renderAt('/')
    const button = await bell()
    expect(button).toHaveAccessibleName('Notifications')
    expect(button).not.toHaveTextContent(/\d/)
  })

  it('shows how many are unread, in its name and as a number, capped at 99+', async () => {
    serve([note(1), note(2), note(3)])
    renderAt('/')
    const button = await screen.findByRole('button', { name: 'Notifications, 3 unread' })
    expect(button).toHaveTextContent('3')
  })

  it('caps a large count', async () => {
    mockApi([], { [`GET ${COUNT}`]: { unread_count: 150 } })
    renderAt('/')
    expect(
      await screen.findByRole('button', { name: 'Notifications, 150 unread' }),
    ).toHaveTextContent('99+')
  })

  it('is not shown, and nothing is polled, while a temporary password must be replaced', async () => {
    const { calls } = serve([note(1)], {}, { password_change_required: true })
    renderAt('/account/password')
    await screen.findAllByText(/password/i)
    expect(screen.queryByRole('button', { name: /^Notifications/ })).not.toBeInTheDocument()
    expect(calls.filter((c) => c.path === COUNT)).toHaveLength(0)
  })
})

describe('keeping the count fresh', () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))

  const countCalls = (calls: Call[]) => calls.filter((c) => c.path === COUNT).length

  it('asks once on load, then once a minute while the tab is visible', async () => {
    const { calls } = serve([note(1)])
    renderAt('/')
    await bell()
    await waitFor(() => expect(countCalls(calls)).toBe(1))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS)
    })
    expect(countCalls(calls)).toBe(2)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS)
    })
    expect(countCalls(calls)).toBe(3)
  })

  it('does not ask while the tab is hidden, and asks again when it is shown', async () => {
    const { calls } = serve([note(1)])
    renderAt('/')
    await bell()
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS * 3)
    })
    expect(countCalls(calls)).toBe(1)
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await waitFor(() => expect(countCalls(calls)).toBe(2))
  })

  it('asks again when the window regains focus', async () => {
    const { calls } = serve([note(1)])
    renderAt('/')
    await bell()
    await act(async () => {
      window.dispatchEvent(new Event('focus'))
    })
    await waitFor(() => expect(countCalls(calls)).toBe(2))
  })

  it('picks up a new notification on the next poll', async () => {
    const state = serve([note(1)])
    renderAt('/')
    await screen.findByRole('button', { name: 'Notifications, 1 unread' })
    state.items.push(note(2))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS)
    })
    expect(
      await screen.findByRole('button', { name: 'Notifications, 2 unread' }),
    ).toBeInTheDocument()
  })

  it('stays silent and keeps the last count when a poll fails', async () => {
    let fail = false
    mockApi([], {
      [`GET ${COUNT}`]: () =>
        fail ? { status: 500, body: { detail: 'down' } } : { body: { unread_count: 4 } },
    })
    renderAt('/')
    await screen.findByRole('button', { name: 'Notifications, 4 unread' })
    fail = true
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS)
    })
    expect(screen.getByRole('button', { name: 'Notifications, 4 unread' })).toBeInTheDocument()
    expect(screen.queryByText(/couldn’t load your notifications/i)).not.toBeInTheDocument()
  })
})

describe('the dropdown', () => {
  it('lists the latest, marks the unread ones, and links to the whole list', async () => {
    const items = [note(1), note(2, { read: true, title: 'Old news' })]
    serve(items)
    renderAt('/')
    fireEvent.click(await bell())
    const panel = await screen.findByRole('dialog', { name: 'Notifications' })
    expect(await within(panel).findByText('Notice 1')).toBeInTheDocument()
    expect(within(panel).getByText('Old news')).toBeInTheDocument()
    expect(within(panel).getByText('Unread:')).toBeInTheDocument() // said to a screen reader
    expect(within(panel).getAllByText('Unread:')).toHaveLength(1) // only the unread one
    expect(within(panel).getAllByText('5 min ago')).toHaveLength(2)
    expect(within(panel).getByRole('link', { name: 'See all notifications' })).toHaveAttribute(
      'href',
      '/notifications',
    )
  })

  it('says plainly when there is nothing', async () => {
    serve([])
    renderAt('/')
    fireEvent.click(await bell())
    expect(await screen.findByText('You’re all caught up.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mark all read' })).toBeDisabled()
  })

  it('opening one marks it read, lowers the count, and closes the panel', async () => {
    const items = [note(1), note(2)]
    const { calls } = serve(items, serveReads(items))
    renderAt('/')
    await screen.findByRole('button', { name: 'Notifications, 2 unread' })
    fireEvent.click(screen.getByRole('button', { name: /^Notifications/ }))
    const first = await screen.findByRole('link', { name: /Notice 1/ })
    expect(first).toHaveAttribute('href', '/courses/1')
    fireEvent.click(first)
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path === `${LIST}1/read/`)).toBe(true),
    )
    expect(
      await screen.findByRole('button', { name: 'Notifications, 1 unread' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Notifications' })).not.toBeInTheDocument()
  })

  it('opening one that is already read sends nothing', async () => {
    const items = [note(1, { read: true }), note(2)]
    const { calls } = serve(items, serveReads(items))
    renderAt('/')
    fireEvent.click(await bell())
    fireEvent.click(await screen.findByRole('link', { name: /Notice 1/ }))
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })

  it('"Mark all read" clears the count and the marks', async () => {
    serve([note(1), note(2)])
    renderAt('/')
    await screen.findByRole('button', { name: 'Notifications, 2 unread' })
    fireEvent.click(screen.getByRole('button', { name: /^Notifications/ }))
    const panel = await screen.findByRole('dialog', { name: 'Notifications' })
    await within(panel).findByText('Notice 1')
    fireEvent.click(within(panel).getByRole('button', { name: 'Mark all read' }))
    expect(await screen.findByRole('button', { name: 'Notifications' })).toBeInTheDocument()
    expect(within(panel).queryByText('Unread:')).not.toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: 'Mark all read' })).toBeDisabled()
  })

  it('says so if the list cannot be loaded', async () => {
    mockApi([], {
      [`GET ${COUNT}`]: { unread_count: 1 },
      [`GET ${LIST}`]: { status: 500, body: { detail: 'down' } },
    })
    renderAt('/')
    fireEvent.click(await bell())
    expect(await screen.findByText(/We couldn’t load your notifications/)).toBeInTheDocument()
  })
})

describe('the Notifications page', () => {
  it('lists everything, newest first, with a heading and the unread marked', async () => {
    serve([note(1), note(2, { read: true })])
    renderAt('/notifications')
    expect(await screen.findByRole('heading', { name: 'Notifications' })).toBeInTheDocument()
    const list = await screen.findByRole('list', { name: 'Your notifications' })
    expect(within(list).getAllByRole('link')).toHaveLength(2)
    expect(within(list).getAllByText('Unread:')).toHaveLength(1)
  })

  it('pages through a long list', async () => {
    const many = Array.from({ length: 25 }, (_, i) => note(i + 1))
    const { calls } = serve(many)
    renderAt('/notifications')
    await screen.findByText('Page 1 of 2')
    expect(screen.getByRole('button', { name: 'Newer' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Older' }))
    await screen.findByText('Page 2 of 2')
    expect(calls.some((c) => c.path === LIST && c.query.get('page') === '2')).toBe(true)
    expect(screen.getByRole('button', { name: 'Older' })).toBeDisabled()
  })

  it('marks everything read from the page, and the bell follows', async () => {
    serve([note(1), note(2)])
    renderAt('/notifications')
    await screen.findByRole('button', { name: 'Notifications, 2 unread' })
    fireEvent.click(await screen.findByRole('button', { name: 'Mark all read' }))
    await screen.findByRole('button', { name: 'Notifications' })
    expect(screen.queryByText('Unread:')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mark all read' })).toBeDisabled()
  })

  it('has an honest empty state', async () => {
    serve([])
    renderAt('/notifications')
    expect(await screen.findByText(/You’re all caught up/)).toBeInTheDocument()
  })

  it('offers a retry when it cannot load', async () => {
    mockApi([], {
      [`GET ${COUNT}`]: { unread_count: 0 },
      [`GET ${LIST}`]: { status: 500, body: { detail: 'down' } },
    })
    renderAt('/notifications')
    expect(await screen.findByText('Couldn’t load your notifications')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again|retry/i })).toBeInTheDocument()
  })
})

describe('a failed refresh', () => {
  it('resolves quietly and leaves the count as it was, never throwing into the page', async () => {
    mockApi([], { [`GET ${COUNT}`]: { status: 500, body: { detail: 'down' } } })
    let refresh: (() => Promise<void>) | undefined
    function Probe() {
      const v = useNotificationCount()
      refresh = v.refresh
      return <p>count {v.unread}</p>
    }
    render(
      <NotificationsProvider enabled={false}>
        <Probe />
      </NotificationsProvider>,
    )
    await expect(refresh?.()).resolves.toBeUndefined()
    expect(screen.getByText('count 0')).toBeInTheDocument()
  })
})

describe('how long ago', () => {
  const now = Date.parse('2026-11-13T12:00:00Z')
  const ago = (ms: number) => new Date(now - ms).toISOString()

  it.each([
    [10_000, 'just now'],
    [5 * 60_000, '5 min ago'],
    [3 * 3_600_000, '3 h ago'],
    [2 * 86_400_000, '2 d ago'],
  ])('%i ms ago reads %s', (ms, text) => {
    expect(timeAgo(ago(ms), now)).toBe(text)
  })

  it('shows a date after a week, and nothing for a bad one', () => {
    expect(timeAgo(ago(10 * 86_400_000), now)).toMatch(/\d/)
    expect(timeAgo('not a date', now)).toBe('')
  })

  it('never shows the future as negative', () => {
    expect(timeAgo(new Date(now + 60_000).toISOString(), now)).toBe('just now')
  })
})
