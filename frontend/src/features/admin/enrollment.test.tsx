import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, page, renderAt, type Call } from './testHelpers'

afterEach(() => vi.unstubAllGlobals())

const ENROLL = ['enrollment.manage_enrollments']
const OPTIONS = {
  courses: [
    {
      id: 1,
      title: 'CX Onboarding',
      modules: [
        { id: 101, title: 'Basics' },
        { id: 102, title: 'Pipelines' },
        { id: 103, title: 'Escalations' },
      ],
    },
    {
      id: 2,
      title: 'Billing basics',
      modules: [{ id: 201, title: 'Invoices' }],
    },
  ],
  programs: [{ id: 5, name: 'March cohort', course_ids: [1, 2] }],
  mentors: [{ id: 9, name: 'Mia Mentor', email: 'mia@e.com' }],
}

const row = (over: object = {}) => ({
  id: 31,
  user: { id: 4, name: 'Lea Learner', email: 'lea@e.com' },
  course: { id: 1, title: 'CX Onboarding', archived: false },
  version: { id: 10, number: 1, latest_number: 1, older: false },
  program: null,
  mentor: null,
  modules: { enabled: 3, total: 3 },
  state: 'active',
  source: 'manual',
  enrolled_at: '2026-10-01T10:00:00Z',
  withdrawn_at: null,
  withdrawn_reason: '',
  ...over,
})

const routes = (rows: object[] = [row()], extra: Record<string, unknown> = {}) => ({
  'GET /api/v1/admin/enrollments/': page(rows),
  'GET /api/v1/admin/enrollments/options/': OPTIONS,
  ...extra,
})

const posts = (calls: Call[], suffix: string) =>
  calls.filter((c) => c.method === 'POST' && c.path.endsWith(suffix))

describe('who sees it', () => {
  it('shows the Enrollments and Groups links only to people who may manage enrollments', async () => {
    mockApi(ENROLL, routes())
    renderAt('/admin/enrollments')
    expect(await screen.findByRole('link', { name: 'Enrollments' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Groups' })).toBeInTheDocument()
  })

  it('refuses the page to anyone else', async () => {
    mockApi(['progress.view_results'], routes())
    renderAt('/admin/enrollments')
    expect(await screen.findByText('You don’t have access to this area')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Enrollments' })).not.toBeInTheDocument()
  })
})

describe('the list', () => {
  it('shows who is on what version, with a mentor or the shared pool', async () => {
    mockApi(
      ENROLL,
      routes([
        row({ mentor: { id: 9, name: 'Mia Mentor', email: 'mia@e.com' } }),
        row({
          id: 32,
          user: { id: 5, name: 'Ola Other', email: 'ola@e.com' },
          version: { id: 9, number: 1, latest_number: 3, older: true },
        }),
      ]),
    )
    renderAt('/admin/enrollments')
    const lea = (await screen.findByText('Lea Learner')).closest('tr')!
    expect(lea).toHaveTextContent('Version 1')
    expect(lea).toHaveTextContent('Mia Mentor')
    const ola = screen.getByText('Ola Other').closest('tr')!
    expect(ola).toHaveTextContent('newest is 3')
    expect(ola).toHaveTextContent('Shared pool')
    expect(within(ola).getByRole('button', { name: 'Move to newest' })).toBeInTheDocument()
    expect(within(lea).queryByRole('button', { name: 'Move to newest' })).not.toBeInTheDocument()
  })

  it('filters by course, group, status and older version', async () => {
    const calls = mockApi(ENROLL, routes())
    renderAt('/admin/enrollments')
    await screen.findByText('Lea Learner')
    fireEvent.change(screen.getByLabelText('Course'), {
      target: { value: '2' },
    })
    await waitFor(() => expect(calls.some((c) => c.query.get('course') === '2')).toBe(true))
    fireEvent.change(screen.getByLabelText('Group'), {
      target: { value: '5' },
    })
    await waitFor(() => expect(calls.some((c) => c.query.get('program') === '5')).toBe(true))
    fireEvent.change(screen.getByLabelText('Status'), {
      target: { value: 'withdrawn' },
    })
    await waitFor(() => expect(calls.some((c) => c.query.get('state') === 'withdrawn')).toBe(true))
    fireEvent.click(screen.getByLabelText('On an older version'))
    await waitFor(() => expect(calls.some((c) => c.query.get('older') === '1')).toBe(true))
  })

  it('says plainly when nobody is enrolled yet', async () => {
    mockApi(ENROLL, routes([]))
    renderAt('/admin/enrollments')
    expect(await screen.findByText(/No one is enrolled yet/)).toBeInTheDocument()
  })

  it('offers to enroll a withdrawn person again', async () => {
    const calls = mockApi(
      ENROLL,
      routes(
        [
          row({
            state: 'withdrawn',
            withdrawn_at: '2026-10-05T10:00:00Z',
            withdrawn_reason: 'Left',
          }),
        ],
        {
          'POST /api/v1/admin/enrollments/31/reenroll/': row(),
        },
      ),
    )
    renderAt('/admin/enrollments')
    const r = (await screen.findByText('Lea Learner')).closest('tr')!
    expect(r).toHaveTextContent('Left')
    fireEvent.click(within(r).getByRole('button', { name: 'Enroll again' }))
    expect(await screen.findByText('Lea Learner is enrolled again.')).toBeInTheDocument()
    expect(posts(calls, '/31/reenroll/')).toHaveLength(1)
  })
})

describe('enrolling people', () => {
  it('picks people and a course, with a mentor, and reports what happened', async () => {
    const calls = mockApi(
      ENROLL,
      routes([], {
        'GET /api/v1/admin/enrollments/people/': {
          results: [
            {
              id: 4,
              name: 'Lea Learner',
              email: 'lea@e.com',
              on_course: false,
            },
            {
              id: 6,
              name: 'Already Here',
              email: 'here@e.com',
              on_course: true,
            },
          ],
        },
        'POST /api/v1/admin/enrollments/': {
          results: [
            {
              user: { id: 4, name: 'Lea Learner', email: 'lea@e.com' },
              outcome: 'enrolled',
            },
          ],
        },
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Enroll people' }))
    const dialog = await screen.findByRole('dialog')
    const enroll = within(dialog).getByRole('button', { name: /^Enroll/ })
    expect(enroll).toBeDisabled()

    fireEvent.change(within(dialog).getByLabelText('Course'), {
      target: { value: '1' },
    })
    fireEvent.change(within(dialog).getByLabelText(/^Mentor/), {
      target: { value: '9' },
    })
    fireEvent.click(await within(dialog).findByRole('checkbox', { name: /Lea Learner/ }))
    expect(within(dialog).getByRole('checkbox', { name: /Already Here/ })).toBeDisabled()
    expect(within(dialog).getByText(/Already on this course/)).toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole('button', { name: /^Enroll 1 person/ }))
    expect(await screen.findByText('Enrollment finished')).toBeInTheDocument()
    const sent = posts(calls, '/enrollments/')[0].body
    expect(sent).toEqual({ user_ids: [4], course_id: 1, mentor_id: 9 })
    expect(screen.getByRole('dialog')).toHaveTextContent('Lea Learner: Enrolled')
  })

  it('can enroll on a whole program', async () => {
    const calls = mockApi(
      ENROLL,
      routes([], {
        'GET /api/v1/admin/enrollments/people/': {
          results: [
            {
              id: 4,
              name: 'Lea Learner',
              email: 'lea@e.com',
              on_course: false,
            },
          ],
        },
        'POST /api/v1/admin/enrollments/': {
          results: [
            {
              user: { id: 4, name: 'Lea Learner', email: 'lea@e.com' },
              outcome: 'program',
              courses: [
                { course_id: 1, outcome: 'enrolled', detail: '' },
                {
                  course_id: 2,
                  outcome: 'skipped',
                  detail: 'That course has no published version yet.',
                },
              ],
            },
          ],
        },
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Enroll people' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByLabelText('A whole group'))
    fireEvent.change(within(dialog).getByLabelText('Group'), {
      target: { value: '5' },
    })
    fireEvent.click(await within(dialog).findByRole('checkbox', { name: /Lea Learner/ }))
    fireEvent.click(within(dialog).getByRole('button', { name: /^Enroll 1 person/ }))
    expect(await screen.findByText(/no published version/)).toBeInTheDocument()
    expect(posts(calls, '/enrollments/')[0].body).toMatchObject({
      user_ids: [4],
      program_id: 5,
    })
  })
})

describe('enrolling from a list', () => {
  const preview = (applied: boolean) => ({
    applied,
    summary: { will_enroll: 1, unknown_email: 1 },
    rows: [
      {
        line: 1,
        email: 'lea@e.com',
        mentor_email: '',
        status: 'will_enroll',
        label: 'Will be enrolled',
        detail: '',
        user: { id: 4, name: 'Lea Learner', email: 'lea@e.com' },
        courses: [{ id: 1, state: applied ? 'done' : 'enroll', detail: '' }],
      },
      {
        line: 2,
        email: 'ghost@e.com',
        mentor_email: '',
        status: 'unknown_email',
        label: 'No account with this email',
        detail: 'Create the account first (People → Users), then enroll them.',
        user: null,
        courses: [],
      },
    ],
  })

  it('previews every row first and only enrolls when confirmed', async () => {
    const calls = mockApi(
      ENROLL,
      routes([], {
        'POST /api/v1/admin/enrollments/bulk/': (c: Call) => ({
          body: preview(c.body?.apply === true),
        }),
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Enroll from a list' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Course'), {
      target: { value: '1' },
    })
    fireEvent.change(within(dialog).getByLabelText('Email addresses'), {
      target: { value: 'lea@e.com\nghost@e.com' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Check the list' }))

    expect(
      await within(dialog).findByText('No account with this email', {
        exact: false,
      }),
    ).toBeInTheDocument()
    expect(within(dialog).getByText('1 will be enrolled. 1 won’t change.')).toBeInTheDocument()
    expect(posts(calls, '/bulk/')).toHaveLength(1)
    expect(posts(calls, '/bulk/')[0].body).toMatchObject({
      apply: false,
      course_id: 1,
    })

    fireEvent.click(within(dialog).getByRole('button', { name: 'Enroll 1 person' }))
    expect(await screen.findByText('List enrolled')).toBeInTheDocument()
    expect(posts(calls, '/bulk/')[1].body).toMatchObject({ apply: true })
    expect(screen.getByText(/Enrolled 1 person/)).toBeInTheDocument()
    // The row that could not be enrolled stays visible afterwards.
    expect(screen.getByText('ghost@e.com')).toBeInTheDocument()
  })

  it('changing the list or target throws away the old preview', async () => {
    mockApi(ENROLL, routes([], { 'POST /api/v1/admin/enrollments/bulk/': preview(false) }))
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Enroll from a list' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Course'), {
      target: { value: '1' },
    })
    fireEvent.change(within(dialog).getByLabelText('Email addresses'), {
      target: { value: 'lea@e.com' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Check the list' }))
    await within(dialog).findByText('1 will be enrolled. 1 won’t change.')
    fireEvent.change(within(dialog).getByLabelText('Email addresses'), {
      target: { value: 'lea@e.com\nx@e.com' },
    })
    expect(within(dialog).getByRole('button', { name: 'Check the list' })).toBeInTheDocument()
    expect(within(dialog).queryByText(/will be enrolled\./)).not.toBeInTheDocument()
  })
})

describe('one row', () => {
  it('changes the mentor', async () => {
    const calls = mockApi(
      ENROLL,
      routes([row()], { 'POST /api/v1/admin/enrollments/31/mentor/': row() }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Mentor' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Mentor'), {
      target: { value: '9' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(
      await screen.findByText(/mentor for CX Onboarding is now Mia Mentor/),
    ).toBeInTheDocument()
    expect(posts(calls, '/31/mentor/')[0].body).toEqual({ mentor_id: 9 })
  })

  it('puts the enrollment in a group that includes its course, or in none', async () => {
    const calls = mockApi(
      ENROLL,
      {
        ...routes([row()], {
          'POST /api/v1/admin/enrollments/31/group/': row(),
        }),
        'GET /api/v1/admin/enrollments/options/': {
          ...OPTIONS,
          programs: [
            { id: 5, name: 'L1', course_ids: [1, 2] },
            { id: 6, name: 'Billing only', course_ids: [2] },
          ],
        },
      },
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Group' }))
    const dialog = await screen.findByRole('dialog')
    const select = within(dialog).getByLabelText('Group')
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'No group',
      'L1',
    ])
    fireEvent.change(select, { target: { value: '5' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Lea Learner is in L1 for CX Onboarding.')).toBeInTheDocument()
    expect(posts(calls, '/31/group/')[0].body).toEqual({ program_id: 5 })
  })

  it('withdraws with a reason, after explaining what it does', async () => {
    const calls = mockApi(
      ENROLL,
      routes([row()], {
        'POST /api/v1/admin/enrollments/31/withdraw/': row({
          state: 'withdrawn',
        }),
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Withdraw' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('Everything they did is kept')
    fireEvent.change(within(dialog).getByLabelText('Reason'), {
      target: { value: 'Left the team' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Withdraw' }))
    expect(
      await screen.findByText('Lea Learner is withdrawn from CX Onboarding.'),
    ).toBeInTheDocument()
    expect(posts(calls, '/31/withdraw/')[0].body).toEqual({
      reason: 'Left the team',
    })
  })

  it('shows a refusal in the dialog and keeps it open', async () => {
    mockApi(
      ENROLL,
      routes([row()], {
        'POST /api/v1/admin/enrollments/31/withdraw/': {
          status: 409,
          body: { detail: 'They are already withdrawn from this course.' },
        },
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Withdraw' }))
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Withdraw' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('already withdrawn')
  })
})

describe('choosing modules', () => {
  const PEOPLE = {
    results: [{ id: 4, name: 'Lea Learner', email: 'lea@e.com', on_course: false }],
  }
  const ENROLLED = {
    results: [
      {
        user: { id: 4, name: 'Lea Learner', email: 'lea@e.com' },
        outcome: 'enrolled',
      },
    ],
  }

  async function openEnroll(extra: Record<string, unknown> = {}) {
    const calls = mockApi(
      ENROLL,
      routes([], {
        'GET /api/v1/admin/enrollments/people/': PEOPLE,
        'POST /api/v1/admin/enrollments/': ENROLLED,
        ...extra,
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Enroll people' }))
    const dialog = await screen.findByRole('dialog')
    return { calls, dialog }
  }

  it('offers every module ticked once a course is chosen, and sends nothing if left alone', async () => {
    const { calls, dialog } = await openEnroll()
    expect(
      within(dialog).queryByRole('group', { name: /Modules they get/ }),
    ).not.toBeInTheDocument()
    fireEvent.change(within(dialog).getByLabelText('Course'), {
      target: { value: '1' },
    })
    const group = within(dialog).getByRole('group', {
      name: /Modules they get/,
    })
    expect(group).toHaveTextContent('3 of 3')
    for (const name of ['Basics', 'Pipelines', 'Escalations']) {
      expect(within(group).getByRole('checkbox', { name })).toBeChecked()
    }
    fireEvent.click(await within(dialog).findByRole('checkbox', { name: /Lea Learner/ }))
    fireEvent.click(within(dialog).getByRole('button', { name: /^Enroll 1 person/ }))
    await screen.findByText('Enrollment finished')
    expect(posts(calls, '/enrollments/')[0].body).not.toHaveProperty('module_ids')
  })

  it('sends only the ticked modules, in course order', async () => {
    const { calls, dialog } = await openEnroll()
    fireEvent.change(within(dialog).getByLabelText('Course'), {
      target: { value: '1' },
    })
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Pipelines' }))
    expect(within(dialog).getByRole('group', { name: /Modules they get/ })).toHaveTextContent(
      '2 of 3',
    )
    fireEvent.click(await within(dialog).findByRole('checkbox', { name: /Lea Learner/ }))
    fireEvent.click(within(dialog).getByRole('button', { name: /^Enroll 1 person/ }))
    await screen.findByText('Enrollment finished')
    expect(posts(calls, '/enrollments/')[0].body).toMatchObject({
      course_id: 1,
      module_ids: [101, 103],
    })
  })

  it('will not enroll with no module ticked, and says why', async () => {
    const { dialog } = await openEnroll()
    fireEvent.change(within(dialog).getByLabelText('Course'), {
      target: { value: '1' },
    })
    fireEvent.click(await within(dialog).findByRole('checkbox', { name: /Lea Learner/ }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'None' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Tick at least one module')
    expect(within(dialog).getByRole('button', { name: /^Enroll 1 person/ })).toBeDisabled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'All' }))
    expect(within(dialog).getByRole('button', { name: /^Enroll 1 person/ })).toBeEnabled()
  })

  it('has nothing to choose for a one-module course or a whole program', async () => {
    const { dialog } = await openEnroll()
    fireEvent.change(within(dialog).getByLabelText('Course'), {
      target: { value: '2' },
    })
    expect(within(dialog).queryByRole('group', { name: /Modules/ })).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('radio', { name: 'A whole group' }))
    fireEvent.change(within(dialog).getByLabelText('Group'), {
      target: { value: '5' },
    })
    expect(within(dialog).queryByRole('group', { name: /Modules/ })).not.toBeInTheDocument()
  })

  it('starts again from every module when another course is chosen', async () => {
    const { dialog } = await openEnroll()
    fireEvent.change(within(dialog).getByLabelText('Course'), {
      target: { value: '1' },
    })
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Basics' }))
    fireEvent.change(within(dialog).getByLabelText('Course'), {
      target: { value: '2' },
    })
    fireEvent.change(within(dialog).getByLabelText('Course'), {
      target: { value: '1' },
    })
    expect(within(dialog).getByRole('checkbox', { name: 'Basics' })).toBeChecked()
  })

  it('applies one choice to a whole list, and a change throws the preview away', async () => {
    const calls = mockApi(
      ENROLL,
      routes([], {
        'POST /api/v1/admin/enrollments/bulk/': {
          applied: false,
          summary: { will_enroll: 1 },
          rows: [
            {
              line: 1,
              email: 'lea@e.com',
              mentor_email: '',
              status: 'will_enroll',
              label: 'Will be enrolled',
              detail: '',
              user: { id: 4, name: 'Lea Learner', email: 'lea@e.com' },
              courses: [{ id: 1, state: 'enroll', detail: '' }],
            },
          ],
        },
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Enroll from a list' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Course'), {
      target: { value: '1' },
    })
    fireEvent.change(within(dialog).getByLabelText('Email addresses'), {
      target: { value: 'lea@e.com' },
    })
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Escalations' }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Check the list' }))
    await within(dialog).findByText('1 will be enrolled. 0 won’t change.')
    expect(posts(calls, '/bulk/')[0].body).toMatchObject({
      apply: false,
      module_ids: [101, 102],
    })

    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Basics' }))
    expect(within(dialog).queryByText(/will be enrolled/)).not.toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Check the list' })).toBeInTheDocument()
  })

  it('shows how many modules a trimmed learner has, and only then', async () => {
    mockApi(
      ENROLL,
      routes([
        row({ modules: { enabled: 2, total: 3 } }),
        row({ id: 32, user: { id: 5, name: 'Ola Other', email: 'ola@e.com' } }),
      ]),
    )
    renderAt('/admin/enrollments')
    const lea = (await screen.findByText('Lea Learner')).closest('tr')!
    expect(lea).toHaveTextContent('2 of 3 modules')
    expect(screen.getByText('Ola Other').closest('tr')).not.toHaveTextContent('modules')
  })

  it('changes a learner’s modules from the row', async () => {
    const calls = mockApi(
      ENROLL,
      routes([row({ modules: { enabled: 2, total: 3 } })], {
        'GET /api/v1/admin/enrollments/31/modules/': {
          active: true,
          modules: [
            { id: 101, title: 'Basics', enabled: true },
            { id: 102, title: 'Pipelines', enabled: false },
            { id: 103, title: 'Escalations', enabled: true },
          ],
        },
        'POST /api/v1/admin/enrollments/31/modules/': row({
          modules: { enabled: 3, total: 3 },
        }),
      }),
    )
    renderAt('/admin/enrollments')
    const r = (await screen.findByText('Lea Learner')).closest('tr')!
    fireEvent.click(within(r).getByRole('button', { name: 'Modules' }))
    const dialog = await screen.findByRole('dialog')
    const save = await within(dialog).findByRole('button', { name: 'Save' })
    expect(save).toBeDisabled() // nothing changed yet
    expect(within(dialog).getByRole('checkbox', { name: 'Pipelines' })).not.toBeChecked()
    expect(dialog).toHaveTextContent('kept and not counted')

    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Pipelines' }))
    expect(save).toBeEnabled()
    fireEvent.click(save)
    expect(
      await screen.findByText('Lea Learner now has 3 of 3 modules of CX Onboarding.'),
    ).toBeInTheDocument()
    expect(posts(calls, '/31/modules/')[0].body).toEqual({
      module_ids: [101, 102, 103],
    })
  })

  it('shows a refusal from the server and keeps the dialog open', async () => {
    mockApi(
      ENROLL,
      routes([row()], {
        'GET /api/v1/admin/enrollments/31/modules/': {
          active: true,
          modules: [
            { id: 101, title: 'Basics', enabled: true },
            { id: 102, title: 'Pipelines', enabled: true },
          ],
        },
        'POST /api/v1/admin/enrollments/31/modules/': {
          status: 409,
          body: {
            detail: 'They have a practice ticket in progress in a module you are switching off.',
          },
        },
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(
      within((await screen.findByText('Lea Learner')).closest('tr')!).getByRole('button', {
        name: 'Modules',
      }),
    )
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(await within(dialog).findByRole('checkbox', { name: 'Pipelines' }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('practice ticket')
  })
})

describe('moving to the newest version', () => {
  const older = row({
    version: { id: 9, number: 1, latest_number: 2, older: true },
  })
  const preview = (carried: boolean) => ({
    blockers: [],
    can_apply: true,
    from: { id: 9, number: 1 },
    to: { id: 12, number: 2 },
    counts: {
      preserved: 2,
      preserved_untouched: 0,
      changed: 1,
      changed_carried: carried ? 1 : 0,
      changed_with_work: 1,
      added: 1,
      removed: 1,
      removed_with_work: 1,
      lessons_kept: carried ? 2 : 1,
      lessons_awaiting: 0,
      lessons_reopened: carried ? 0 : 1,
      lessons_left: 0,
    },
    lessons: [
      {
        id: 21,
        title: 'Second',
        module: 'Module',
        outcome: carried ? 'kept' : 'reopened',
        activities: [
          {
            id: 55,
            title: 'Later',
            type: 'reading',
            status: 'changed',
            work: ['progress'],
            has_work: true,
            fields: ['source_url'],
            conflict: false,
            carried,
            can_carry: true,
          },
          {
            id: 56,
            title: 'New',
            type: 'reading',
            status: 'added',
            work: [],
            has_work: false,
            fields: [],
            conflict: false,
            carried: false,
            can_carry: false,
          },
        ],
      },
    ],
    removed: [
      {
        id: 60,
        title: 'Old',
        type: 'reading',
        lesson: 'Second',
        has_work: true,
      },
    ],
    left_lessons: [],
  })

  it('explains each category, lets a change be carried over, and confirms', async () => {
    const calls = mockApi(
      ENROLL,
      routes([older], {
        'POST /api/v1/admin/enrollments/31/migration/': (c: Call) => ({
          body: preview(Array.isArray(c.body?.carry) && (c.body?.carry as number[]).includes(55)),
        }),
        'POST /api/v1/admin/enrollments/31/migrate/': {
          result: preview(true),
          enrollment: row(),
        },
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Move to newest' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/This is exactly what will happen/)).toBeInTheDocument()
    expect(dialog).toHaveTextContent('2 results carried over')
    expect(dialog).toHaveTextContent('1 new activity starts empty')
    expect(dialog).toHaveTextContent('stays on version 1 as history')
    expect(dialog).toHaveTextContent('Needs doing again')
    expect(dialog).toHaveTextContent('source url')
    expect(dialog).toHaveTextContent('No longer in the course')

    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Carry over Later' }))
    await within(dialog).findByText('Stays complete.')
    expect(calls.filter((c) => c.path.endsWith('/31/migration/')).at(-1)?.body).toEqual({
      carry: [55],
      new_modules_off: [],
    })

    fireEvent.click(within(dialog).getByRole('button', { name: 'Move to version 2' }))
    expect(
      await screen.findByText('Lea Learner is now on version 2 of CX Onboarding.'),
    ).toBeInTheDocument()
    expect(posts(calls, '/31/migrate/')[0].body).toEqual({
      to_version_id: 12,
      carry: [55],
      new_modules_off: [],
    })
  })

  it('lists new modules with a toggle, and what stays off', async () => {
    const withModules = (newOff: number[]) => ({
      ...preview(false),
      modules: [
        { id: 301, title: 'Basics', status: 'on', enabled: true },
        { id: 302, title: 'Pipelines', status: 'off', enabled: false },
        {
          id: 303,
          title: 'Reporting',
          status: 'new',
          enabled: !newOff.includes(303),
        },
      ],
    })
    const calls = mockApi(
      ENROLL,
      routes([older], {
        'POST /api/v1/admin/enrollments/31/migration/': (c: Call) => ({
          body: withModules((c.body?.new_modules_off as number[]) ?? []),
        }),
        'POST /api/v1/admin/enrollments/31/migrate/': {
          result: preview(false),
          enrollment: row(),
        },
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Move to newest' }))
    const dialog = await screen.findByRole('dialog')
    const give = await within(dialog).findByRole('checkbox', {
      name: 'Give them Reporting',
    })
    expect(give).toBeChecked() // new modules are on unless the trainer says otherwise
    expect(dialog).toHaveTextContent('new in this version')
    expect(dialog).toHaveTextContent('Pipelines')
    expect(dialog).toHaveTextContent('stays off')
    expect(within(dialog).queryByRole('checkbox', { name: /Pipelines/ })).not.toBeInTheDocument()

    fireEvent.click(give)
    await waitFor(() =>
      expect(calls.filter((c) => c.path.endsWith('/31/migration/')).at(-1)?.body).toMatchObject({
        new_modules_off: [303],
      }),
    )
    expect(
      await within(dialog).findByRole('checkbox', {
        name: 'Give them Reporting',
      }),
    ).not.toBeChecked()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Move to version 2' }))
    await screen.findByText('Lea Learner is now on version 2 of CX Onboarding.')
    expect(posts(calls, '/31/migrate/')[0].body).toMatchObject({
      new_modules_off: [303],
    })
  })

  it('shows no module section when every module simply stays on', async () => {
    mockApi(
      ENROLL,
      routes([older], {
        'POST /api/v1/admin/enrollments/31/migration/': {
          ...preview(false),
          modules: [{ id: 301, title: 'Basics', status: 'on', enabled: true }],
        },
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Move to newest' }))
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText(/This is exactly what will happen/)
    expect(within(dialog).queryByRole('heading', { name: 'Modules' })).not.toBeInTheDocument()
  })

  it('shows what blocks a move and does not offer it', async () => {
    mockApi(
      ENROLL,
      routes([older], {
        'POST /api/v1/admin/enrollments/31/migration/': {
          blockers: [
            'They have a practice ticket in progress. Let them finish it or close it, then move them.',
          ],
          can_apply: false,
          from: { id: 9, number: 1 },
          to: { id: 12, number: 2 },
        },
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Move to newest' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/practice ticket in progress/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Move to version 2' })).toBeDisabled()
  })

  it('tells the trainer to look again when a newer version appeared meanwhile', async () => {
    mockApi(
      ENROLL,
      routes([older], {
        'POST /api/v1/admin/enrollments/31/migration/': preview(false),
        'POST /api/v1/admin/enrollments/31/migrate/': {
          status: 409,
          body: {
            detail: 'A newer version was published since you looked. Open the preview again.',
          },
        },
      }),
    )
    renderAt('/admin/enrollments')
    fireEvent.click(await screen.findByRole('button', { name: 'Move to newest' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Move to version 2' }))
    expect(await within(dialog).findByText(/newer version was published/)).toBeInTheDocument()
  })
})

describe('programs', () => {
  const program = (over: object = {}) => ({
    id: 5,
    name: 'March cohort',
    description: 'March hires',
    starts_on: '2026-03-01',
    ends_on: null,
    archived: false,
    members: 3,
    courses: [
      {
        course_id: 1,
        title: 'CX Onboarding',
        required: true,
        published: true,
        archived: false,
      },
      {
        course_id: 2,
        title: 'Billing basics',
        required: false,
        published: false,
        archived: false,
      },
    ],
    ...over,
  })
  const base = (rows: object[] = [program()]) => ({
    'GET /api/v1/admin/programs/': { results: rows },
    'GET /api/v1/admin/enrollments/options/': OPTIONS,
  })

  it('lists programs with their courses and people', async () => {
    mockApi(ENROLL, base())
    renderAt('/admin/programs')
    const r = (await screen.findByText('March cohort')).closest('tr')!
    expect(r).toHaveTextContent('Billing basics')
    expect(r).toHaveTextContent('optional')
    expect(r).toHaveTextContent('not published')
  })

  it('creates a program with ordered courses', async () => {
    const calls = mockApi(ENROLL, {
      ...base([]),
      'POST /api/v1/admin/programs/': program(),
    })
    renderAt('/admin/programs')
    fireEvent.click(await screen.findByRole('button', { name: 'New group' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Name'), {
      target: { value: 'April cohort' },
    })
    fireEvent.change(within(dialog).getByLabelText('Add a course'), {
      target: { value: '1' },
    })
    fireEvent.change(within(dialog).getByLabelText('Add a course'), {
      target: { value: '2' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Move Billing basics up' }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('April cohort is created.')).toBeInTheDocument()
    expect(posts(calls, '/programs/')[0].body).toMatchObject({
      name: 'April cohort',
      courses: [
        { course_id: 2, required: true },
        { course_id: 1, required: true },
      ],
    })
  })

  it('archives a program and catches existing members up', async () => {
    const calls = mockApi(ENROLL, {
      ...base(),
      'POST /api/v1/admin/programs/5/archive/': program({ archived: true }),
      'POST /api/v1/admin/programs/5/enroll-missing/': {
        people: 3,
        enrolled: 3,
        skipped: 0,
        program: program(),
      },
    })
    renderAt('/admin/programs')
    fireEvent.click(await screen.findByRole('button', { name: 'Enroll missing' }))
    expect(await screen.findByText('Enrolled 3 new enrollments for 3 people.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Archive' }))
    expect(await screen.findByText('March cohort is archived.')).toBeInTheDocument()
    expect(posts(calls, '/5/archive/')).toHaveLength(1)
  })

  it('shows a refusal from the server', async () => {
    mockApi(ENROLL, {
      ...base([]),
      'POST /api/v1/admin/programs/': {
        status: 409,
        body: { detail: 'There is already a group with that name.' },
      },
    })
    renderAt('/admin/programs')
    fireEvent.click(await screen.findByRole('button', { name: 'New group' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Name'), {
      target: { value: 'Dup' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('already a group')
  })
})
