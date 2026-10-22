import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { StageStepper } from '../features/studio/StageStepper'
import { Dialog } from './Dialog'
import { Popover } from './Popover'

function Harness({ onClose = () => {} }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}>Open</button>
      {open && (
        <Dialog
          title="Sure?"
          onClose={() => {
            onClose()
            setOpen(false)
          }}
          actions={
            <>
              <button>Cancel</button>
              <button>Confirm</button>
            </>
          }
        >
          Body
        </Dialog>
      )}
    </>
  )
}

describe('Dialog', () => {
  it('takes focus, traps Tab, closes on Escape and returns focus to the opener', () => {
    const onClose = vi.fn()
    render(<Harness onClose={onClose} />)
    const opener = screen.getByRole('button', { name: 'Open' })
    opener.focus()
    fireEvent.click(opener)

    const dialog = screen.getByRole('dialog', { name: 'Sure?' })
    expect(dialog).toHaveFocus()

    const confirm = screen.getByRole('button', { name: 'Confirm' })
    confirm.focus()
    fireEvent.keyDown(document, { key: 'Tab' }) // last → wraps to first
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true }) // first → wraps to last
    expect(confirm).toHaveFocus()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('closes when the backdrop is clicked', () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: 'Open' }))
    const backdrop = document.querySelector('[class*="backdrop"]') as HTMLElement
    fireEvent.click(backdrop)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('starts alert dialogs on the safe (first) button', () => {
    render(
      <Dialog title="Delete?" role="alertdialog" onClose={() => {}} actions={<><button>Cancel</button><button>Delete</button></>}>
        This can’t be undone.
      </Dialog>,
    )
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })
})

describe('Popover', () => {
  function PopoverHarness() {
    return (
      <Popover
        label="Things"
        trigger={(props) => <button {...props}>Menu</button>}
      >
        {(close) => <button onClick={close}>Item</button>}
      </Popover>
    )
  }

  it('opens, reports expanded state, and closes on Escape with focus back on the trigger', () => {
    render(<PopoverHarness />)
    const trigger = screen.getByRole('button', { name: 'Menu' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('dialog', { name: 'Things' })).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('closes on an outside click and when an item asks it to', () => {
    render(<PopoverHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'Menu' }))
    fireEvent.mouseDown(document.body)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }))
    fireEvent.click(screen.getByRole('button', { name: 'Item' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('StageStepper', () => {
  const stage = (key: Parameters<typeof StageStepper>[0]['status']['key'], label: string = key) => (
    <StageStepper status={{ key, label }} />
  )

  it('marks the current step with aria-current and says what is done in words', () => {
    const { container } = render(stage('in_review', 'In review'))
    const current = container.querySelector('[aria-current="step"]')
    expect(current).toHaveTextContent('Review')
    expect(screen.getByText('Build').parentElement).toHaveTextContent('(done)')
  })

  it('shows a published course as fully through the pipeline', () => {
    const { container } = render(stage('published', 'Published v1'))
    expect(container.querySelector('[aria-current="step"]')).toHaveTextContent('Live')
  })

  it('a published course being edited is back at Build, with the old version still live', () => {
    const { container } = render(stage('published_with_draft', 'Published v1 · edits in draft'))
    expect(container.querySelector('[aria-current="step"]')).toHaveTextContent('Build')
    expect(screen.getByText('Live').parentElement).toHaveTextContent('previous version is live')
  })
})
