import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { parseCourseIntro } from './courseIntro'
import { LessonContent } from './LessonContent'
import { parseFlow } from './lesson/parseFlow'
import { extractOutline } from './lesson/outline'

describe('callouts', () => {
  const md = `> [!IDEA]
> A mode is a promise.

> [!WHY]
> Place the problem first.

> [!SUPPORT]
> Ask for one record.

> [!SCENARIO] The stale table
> > “It hasn't updated since 10:30.”
>
> **Recognise:** the source has it.

> [!PITFALL]
> Don't say lost.

> [!TAKEAWAY]
> - One
> - Two

> just a plain quote`

  it('renders each kind as a labelled note, with its optional title', () => {
    render(<LessonContent markdown={md} />)
    const labels = ['Key idea', 'Why this matters', 'Support lens', 'Customer scenario', 'Common pitfall', 'Takeaway']
    for (const label of labels) {
      expect(screen.getByRole('note', { name: label })).toBeInTheDocument()
    }
    const scenario = screen.getByRole('note', { name: 'Customer scenario' })
    expect(within(scenario).getByText('The stale table')).toBeInTheDocument()
    expect(within(scenario).getByText(/hasn't updated since 10:30/)).toBeInTheDocument()
    // The marker text itself never leaks into the rendered body.
    expect(screen.queryByText(/\[!/)).not.toBeInTheDocument()
  })

  it('keeps list structure inside a takeaway', () => {
    render(<LessonContent markdown={md} />)
    const takeaway = screen.getByRole('note', { name: 'Takeaway' })
    expect(within(takeaway).getAllByRole('listitem')).toHaveLength(2)
  })

  it('leaves a plain blockquote as a quote, not a callout', () => {
    const { container } = render(<LessonContent markdown={md} />)
    expect(screen.getAllByRole('note')).toHaveLength(6)
    expect(container.textContent).toContain('just a plain quote')
  })

  it('still does not render raw HTML', () => {
    const { container } = render(
      <LessonContent markdown={'> [!IDEA]\n> <script>alert(1)</script> <b>x</b>'} />,
    )
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
  })
})

describe('flow diagrams', () => {
  it('parses a chain and its highlighted step', () => {
    expect(parseFlow('Source -> Extract -> Load*')).toEqual([
      { label: 'Source', highlight: false },
      { label: 'Extract', highlight: false },
      { label: 'Load', highlight: true },
    ])
  })

  it('rejects anything that is not a chain of two or more steps', () => {
    expect(parseFlow('just one thing')).toBeNull()
    expect(parseFlow('A ->')).toBeNull()
    expect(parseFlow('')).toBeNull()
  })

  it('renders an ordered, labelled list with the focus step marked', () => {
    render(<LessonContent markdown={'```flow\nSource -> Extract* -> Load\n```'} />)
    const flow = screen.getByRole('group', { name: 'Flow: Source, then Extract, then Load' })
    const steps = within(flow).getAllByRole('listitem')
    expect(steps.map((s) => s.textContent)).toEqual(['Source', 'Extract', 'Load'])
    expect(steps[1]).toHaveAttribute('aria-current', 'step')
    expect(steps[0]).not.toHaveAttribute('aria-current')
  })

  it('falls back to a plain code block when the flow is malformed', () => {
    const { container } = render(<LessonContent markdown={'```flow\nnot a chain\n```'} />)
    expect(screen.queryByRole('group')).not.toBeInTheDocument()
    expect(container.querySelector('pre')).not.toBeNull()
  })
})

describe('section ids and outline', () => {
  const md = '## The big picture\n\ntext\n\n```\n## not a heading\n```\n\n## Two ends, two sets of rules\n\nmore'

  it('extracts ## sections and skips code fences', () => {
    expect(extractOutline(md)).toEqual([
      { id: 'the-big-picture', text: 'The big picture' },
      { id: 'two-ends-two-sets-of-rules', text: 'Two ends, two sets of rules' },
    ])
  })

  it('puts matching ids on the rendered headings so outline links resolve', () => {
    render(<LessonContent markdown={md} />)
    for (const { id, text } of extractOutline(md)) {
      expect(screen.getByRole('heading', { level: 2, name: text })).toHaveAttribute('id', id)
    }
  })
})

describe('parseCourseIntro', () => {
  it('splits the lead from the "What you’ll learn" bullets', () => {
    const intro = parseCourseIntro('Lead one.\n\nLead two.\n\n## What you’ll learn\n\n- A\n- B\n')
    expect(intro.lead).toEqual(['Lead one.', 'Lead two.'])
    expect(intro.outcomes).toEqual(['A', 'B'])
  })

  it('handles a description with no outcomes section', () => {
    expect(parseCourseIntro('Just a blurb.')).toEqual({ lead: ['Just a blurb.'], outcomes: [] })
    expect(parseCourseIntro('')).toEqual({ lead: [], outcomes: [] })
  })
})
