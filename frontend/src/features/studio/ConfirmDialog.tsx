import type { ReactNode } from 'react'

import { Dialog } from '../../components/Dialog'

interface Props {
  title: string
  children: ReactNode
  confirmLabel: string
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** A destructive confirmation: Cancel is focused first. */
export function ConfirmDialog({ title, children, confirmLabel, busy, onConfirm, onCancel }: Props) {
  return (
    <Dialog
      title={title}
      role="alertdialog"
      width={440}
      onClose={onCancel}
      actions={
        <>
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn btn-danger" disabled={busy} onClick={onConfirm}>
            {busy ? 'Working…' : confirmLabel}
          </button>
        </>
      }
    >
      {children}
    </Dialog>
  )
}
