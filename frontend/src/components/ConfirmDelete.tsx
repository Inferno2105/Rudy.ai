import { Trash2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Button } from './ui/button'
import { Dialog, DialogClose, DialogContent, DialogTrigger } from './ui/dialog'
import { Callout } from './ui/feedback'

/**
 * A delete button that asks first. Deleting cannot be undone, so the dialog
 * says exactly what goes and what stays, and shows the server's refusal
 * (e.g. "still processing") verbatim instead of closing.
 */
export function ConfirmDelete({
  trigger,
  title,
  children,
  confirmLabel,
  onConfirm,
}: {
  /** The button that opens the dialog. */
  trigger: ReactNode
  title: string
  children: ReactNode
  confirmLabel: string
  /** Performs the deletion; reject to keep the dialog open with the error. */
  onConfirm: () => Promise<unknown>
}) {
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function confirm() {
    setPending(true)
    setError(null)
    try {
      await onConfirm()
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) setError(null)
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent title={title}>
        <div className="text-muted space-y-3 text-sm">{children}</div>
        {error ? (
          <div className="mt-4">
            <Callout tone="danger" announce="alert">
              {error}
            </Callout>
          </div>
        ) : null}
        <div className="mt-6 flex justify-end gap-2">
          <DialogClose asChild>
            <Button variant="ghost">Cancel</Button>
          </DialogClose>
          <Button variant="danger" onClick={() => void confirm()} disabled={pending}>
            <Trash2 aria-hidden /> {pending ? 'Deleting…' : confirmLabel}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
