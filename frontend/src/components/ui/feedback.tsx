import { AlertTriangle, CircleAlert, Info } from 'lucide-react'
import type { HTMLAttributes, ReactNode } from 'react'

import { cn } from '../../lib/utils'

type CalloutTone = 'info' | 'warning' | 'danger'

const CALLOUT: Record<CalloutTone, { className: string; Icon: typeof Info }> = {
  info: { className: 'bg-accent-soft text-fg ring-accent/20', Icon: Info },
  warning: { className: 'bg-warning-soft text-fg ring-warning/30', Icon: AlertTriangle },
  danger: { className: 'bg-danger-soft text-fg ring-danger/25', Icon: CircleAlert },
}

const ICON_TONE: Record<CalloutTone, string> = {
  info: 'text-accent',
  warning: 'text-warning',
  danger: 'text-danger',
}

export function Callout({
  tone = 'info',
  title,
  children,
  className,
  announce,
}: {
  tone?: CalloutTone
  title?: ReactNode
  children?: ReactNode
  className?: string
  /** Announce to screen readers: politely (status) or immediately (alert). */
  announce?: 'alert' | 'status'
}) {
  const { className: toneClass, Icon } = CALLOUT[tone]
  // A status callout is an <output> (implicit role="status"); an alert keeps role="alert".
  const Element = announce === 'status' ? 'output' : 'div'
  return (
    <Element
      role={announce === 'alert' ? 'alert' : undefined}
      className={cn(
        'flex gap-3 rounded-lg px-4 py-3 text-sm ring-1 ring-inset',
        toneClass,
        className,
      )}
    >
      <Icon className={cn('mt-0.5 size-4 shrink-0', ICON_TONE[tone])} aria-hidden />
      <div className="min-w-0 space-y-1">
        {title ? <p className="font-medium">{title}</p> : null}
        {children ? <div className="text-muted break-words">{children}</div> : null}
      </div>
    </Element>
  )
}

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn(
        'animate-shimmer rounded-md bg-[linear-gradient(90deg,var(--color-subtle),color-mix(in_oklch,var(--color-accent)_14%,var(--color-subtle)),var(--color-subtle))] bg-[length:200%_100%]',
        className,
      )}
      {...props}
    />
  )
}

/** Accessible loading placeholder for a whole region. */
export function LoadingBlock({ label, lines = 4 }: { label: string; lines?: number }) {
  return (
    <output className="block space-y-3">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn('h-4', i % 3 === 2 ? 'w-2/3' : 'w-full')} />
      ))}
      <span className="sr-only">{label}</span>
    </output>
  )
}

export function EmptyState({
  icon,
  title,
  children,
  action,
  className,
}: {
  icon?: ReactNode
  title: ReactNode
  children?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn('flex flex-col items-center justify-center px-6 py-12 text-center', className)}
    >
      {icon ? (
        <div className="animate-float relative mb-5" aria-hidden>
          <div className="bg-brand absolute inset-0 rounded-2xl opacity-40 blur-xl" />
          <div className="glass text-accent relative grid size-14 place-items-center rounded-2xl [&_svg]:size-6">
            {icon}
          </div>
        </div>
      ) : null}
      <p className="font-display text-fg text-lg font-semibold">{title}</p>
      {children ? <div className="text-muted mt-1 max-w-md text-sm">{children}</div> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  )
}
