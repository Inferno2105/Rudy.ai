import { X } from 'lucide-react'
import { Toast as ToastPrimitive } from 'radix-ui'
import { useCallback, useMemo, useState, type ReactNode } from 'react'

import { cn } from '../../lib/utils'
import { ToastContext, type Notify, type ToastMessage } from './toast-context'

let nextId = 1

/** Radix Toast: announced to screen readers, dismissible, swipeable, pauses on hover. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([])

  const notify = useCallback<Notify>((toast) => {
    setToasts((current) => [...current, { ...toast, id: nextId++ }])
  }, [])

  const remove = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const value = useMemo(() => notify, [notify])

  return (
    <ToastContext.Provider value={value}>
      <ToastPrimitive.Provider swipeDirection="right" duration={6000}>
        {children}
        {toasts.map((toast) => (
          <ToastPrimitive.Root
            key={toast.id}
            type={toast.tone === 'danger' ? 'foreground' : 'background'}
            onOpenChange={(open) => {
              if (!open) remove(toast.id)
            }}
            className={cn(
              'bg-surface ring-border relative flex items-start gap-3 rounded-lg p-4 pr-10 shadow-lg ring-1',
              'data-[swipe=end]:translate-x-[var(--radix-toast-swipe-end-x)] data-[swipe=move]:translate-x-[var(--radix-toast-swipe-move-x)]',
            )}
          >
            <span
              aria-hidden
              className={cn(
                'mt-1.5 size-2 shrink-0 rounded-full',
                toast.tone === 'success' && 'bg-success',
                toast.tone === 'danger' && 'bg-danger',
                toast.tone === 'info' && 'bg-accent',
              )}
            />
            <div className="min-w-0">
              <ToastPrimitive.Title className="text-fg text-sm font-medium">
                {toast.title}
              </ToastPrimitive.Title>
              {toast.description ? (
                <ToastPrimitive.Description className="text-muted mt-0.5 text-sm break-words">
                  {toast.description}
                </ToastPrimitive.Description>
              ) : null}
            </div>
            <ToastPrimitive.Close
              aria-label="Dismiss"
              className="text-muted hover:bg-subtle hover:text-fg absolute top-3 right-3 rounded p-0.5"
            >
              <X className="size-4" aria-hidden />
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        ))}
        <ToastPrimitive.Viewport className="focus-visible:outline-ring fixed right-0 bottom-0 z-50 flex w-full max-w-sm flex-col gap-2 p-4 focus-visible:outline-2" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  )
}
