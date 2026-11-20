import { fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderAt } from '../admin/testHelpers'

afterEach(() => vi.unstubAllGlobals())

const CERT = {
  code: 'ABCDEFGHJK',
  name: 'Lea Learner',
  employee_id: 'E123',
  course_title: 'Support basics',
  course_id: 1,
  issued_at: '2026-11-12T10:00:00Z',
  score: 0.86,
  threshold: 70,
  revoked: false,
}

describe('Certificate page', () => {
  it('shows who, what, when, the score against the pass mark and the id', async () => {
    mockApi([], { 'GET /api/v1/certificates/ABCDEFGHJK/': CERT })
    renderAt('/certificates/ABCDEFGHJK')
    const sheet = await screen.findByRole('article', { name: 'Certificate' })
    for (const text of [
      'Lea Learner',
      'Employee ID E123',
      'Support basics',
      '86% (pass mark 70%)',
      'ABCDEFGHJK',
      '2026',
    ]) {
      expect(sheet).toHaveTextContent(text)
    }
  })

  it('prints from the browser (which can save it as a PDF)', async () => {
    const print = vi.fn()
    vi.stubGlobal('print', print)
    mockApi([], { 'GET /api/v1/certificates/ABCDEFGHJK/': CERT })
    renderAt('/certificates/ABCDEFGHJK')
    fireEvent.click(await screen.findByRole('button', { name: 'Print or save as PDF' }))
    expect(print).toHaveBeenCalled()
  })

  it('says "Completed" for a course with no scored work', async () => {
    mockApi([], { 'GET /api/v1/certificates/ABCDEFGHJK/': { ...CERT, score: null } })
    renderAt('/certificates/ABCDEFGHJK')
    expect(await screen.findByRole('article', { name: 'Certificate' })).toHaveTextContent(
      'Completed',
    )
  })

  it('says plainly when there is no such certificate (or it is not theirs)', async () => {
    mockApi([], {})
    renderAt('/certificates/NOPE')
    expect(await screen.findByText('Certificate not found')).toBeInTheDocument()
  })
})
