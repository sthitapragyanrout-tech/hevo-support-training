import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, page, renderAt } from './testHelpers'

const AUTHOR = 'catalog.author_content'
const PUBLISH = 'catalog.publish_courseversion'

afterEach(() => vi.unstubAllGlobals())

const LIVE = {
  id: 1,
  title: 'CX Onboarding',
  slug: 'cx-onboarding',
  status: { key: 'published', label: 'Published v2' },
  created_by: 'trn@example.com',
  created_at: '2026-09-01T10:00:00Z',
  archived_at: null,
  versions: 2,
  published_version: 2,
}
const DRAFT = {
  ...LIVE,
  id: 2,
  title: 'Escalations',
  slug: 'escalations',
  status: { key: 'draft', label: 'Draft' },
  versions: 1,
  published_version: null,
}
const OLD = {
  ...LIVE,
  id: 3,
  title: 'Retired course',
  slug: 'retired',
  status: { key: 'archived', label: 'Archived' },
  archived_at: '2026-10-01T10:00:00Z',
}

const DETAIL = {
  ...LIVE,
  can_archive: true,
  versions_history: [
    {
      id: 20,
      number: 2,
      state: 'published',
      state_label: 'Published',
      title: 'CX Onboarding',
      lessons: 5,
      activities: 9,
      learners: 12,
      submitted_at: '2026-10-01T09:00:00Z',
      submitted_by: 'trn@example.com',
      published_at: '2026-10-02T09:00:00Z',
      published_by: 'adm@example.com',
    },
    {
      id: 10,
      number: 1,
      state: 'archived',
      state_label: 'Archived',
      title: 'CX Onboarding',
      lessons: 3,
      activities: 4,
      learners: 30,
      submitted_at: null,
      submitted_by: null,
      published_at: '2026-09-02T09:00:00Z',
      published_by: 'adm@example.com',
    },
  ],
}

describe('Courses list', () => {
  const routes = { 'GET /api/v1/admin/courses/': page([LIVE, DRAFT, OLD]) }

  it('shows every course with its state, versions and who made it', async () => {
    mockApi([AUTHOR], routes)
    renderAt('/admin/courses')
    const live = (await screen.findByRole('link', { name: /CX Onboarding/ })).closest('tr')!
    expect(live).toHaveTextContent('cx-onboarding')
    expect(live).toHaveTextContent('Published v2')
    expect(live).toHaveTextContent('trn@example.com')
    expect(screen.getByRole('link', { name: /CX Onboarding/ })).toHaveAttribute('href', '/admin/courses/1')
    expect(screen.getByRole('link', { name: /Retired course/ }).closest('tr')).toHaveTextContent('Archived')
    expect(screen.getByRole('link', { name: /Escalations/ }).closest('tr')).toHaveTextContent('Draft')
  })

  it('is in the rail for authors and publishers, and not for others', async () => {
    mockApi([AUTHOR], routes)
    renderAt('/admin/courses')
    const rail = await screen.findByRole('navigation', { name: 'Admin sections' })
    expect(within(rail).getByRole('link', { name: 'Courses' })).toBeInTheDocument()
  })

  it('is closed to anyone without authoring or publishing rights', async () => {
    mockApi(['progress.view_results'], routes)
    renderAt('/admin/courses')
    expect(await screen.findByText('You don’t have access to this area')).toBeInTheDocument()
  })

  it('searches and filters by status', async () => {
    const calls = mockApi([AUTHOR], routes)
    renderAt('/admin/courses')
    await screen.findByRole('link', { name: /CX Onboarding/ })
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'archived' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('status') === 'archived')).toBe(true))
    fireEvent.change(screen.getByLabelText('Search courses'), { target: { value: 'cx' } })
    await waitFor(() => expect(calls.some((c) => c.query.get('search') === 'cx')).toBe(true))
  })

  it('says so when nothing matches', async () => {
    mockApi([AUTHOR], { 'GET /api/v1/admin/courses/': page([]) })
    renderAt('/admin/courses')
    expect(await screen.findByText('There are no courses yet.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search courses'), { target: { value: 'zzz' } })
    expect(await screen.findByText('No courses match.')).toBeInTheDocument()
  })
})

describe('Course detail', () => {
  const base = { 'GET /api/v1/admin/courses/1/': { body: DETAIL } }

  it('shows the version history: state, content, learners, who published and when', async () => {
    mockApi([AUTHOR, PUBLISH], base)
    renderAt('/admin/courses/1')
    expect(await screen.findByRole('heading', { name: 'CX Onboarding' })).toBeInTheDocument()
    const rows = within(screen.getByRole('table')).getAllByRole('row')
    expect(rows).toHaveLength(3)
    expect(rows[1]).toHaveTextContent('v2')
    expect(rows[1]).toHaveTextContent('5 lessons · 9 activities')
    expect(rows[1]).toHaveTextContent('12')
    expect(rows[1]).toHaveTextContent('by adm@example.com')
    expect(rows[2]).toHaveTextContent('Archived')
    expect(rows[2]).toHaveTextContent('30')
  })

  it('links to Studio for authors, and not for an archived course', async () => {
    mockApi([AUTHOR, PUBLISH], base)
    renderAt('/admin/courses/1')
    expect(await screen.findByRole('link', { name: 'Open in Studio' })).toHaveAttribute('href', '/studio/courses/1')
  })

  it('does not offer archiving to someone who cannot', async () => {
    mockApi([AUTHOR], { 'GET /api/v1/admin/courses/1/': { body: { ...DETAIL, can_archive: false } } })
    renderAt('/admin/courses/1')
    await screen.findByRole('heading', { name: 'CX Onboarding' })
    expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument()
  })

  it('asks before archiving, then archives, and says what changed', async () => {
    let archived = false
    const calls = mockApi([AUTHOR, PUBLISH], {
      'GET /api/v1/admin/courses/1/': () => ({
        body: archived
          ? { ...DETAIL, status: { key: 'archived', label: 'Archived' }, archived_at: '2026-10-23T10:00:00Z' }
          : DETAIL,
      }),
      'POST /api/v1/admin/courses/1/archive/': () => {
        archived = true
        return { body: OLD }
      },
    })
    renderAt('/admin/courses/1')
    fireEvent.click(await screen.findByRole('button', { name: 'Archive' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('Their existing progress and scores are kept')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Archive' }))

    expect(await screen.findByRole('button', { name: 'Restore' })).toBeInTheDocument()
    expect(screen.getByText('Archived. Learners can no longer see it.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Open in Studio' })).not.toBeInTheDocument()
  })

  it('restores an archived course', async () => {
    let archived = true
    mockApi([AUTHOR, PUBLISH], {
      'GET /api/v1/admin/courses/1/': () => ({
        body: archived ? { ...DETAIL, status: { key: 'archived', label: 'Archived' } } : DETAIL,
      }),
      'POST /api/v1/admin/courses/1/restore/': () => {
        archived = false
        return { body: LIVE }
      },
    })
    renderAt('/admin/courses/1')
    fireEvent.click(await screen.findByRole('button', { name: 'Restore' }))
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Restore' }))
    expect(await screen.findByText('Restored. Learners can see it again.')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Archive' })).toBeInTheDocument()
  })

  it('shows the server’s reason when archiving is refused', async () => {
    mockApi([AUTHOR, PUBLISH], {
      ...base,
      'POST /api/v1/admin/courses/1/archive/': { status: 403, body: { detail: 'You do not have permission.' } },
    })
    renderAt('/admin/courses/1')
    fireEvent.click(await screen.findByRole('button', { name: 'Archive' }))
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Archive' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have permission.')
  })

  it('handles an unknown course', async () => {
    mockApi([AUTHOR], {})
    renderAt('/admin/courses/99')
    expect(await screen.findByText('Course not found')).toBeInTheDocument()
  })
})
