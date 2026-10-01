import type { HTMLAttributes, ReactNode } from 'react'

import { cn } from '../../lib/utils'

export function Card({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={cn('bg-surface ring-border rounded-xl shadow-xs ring-1', className)}
      {...props}
    />
  )
}

export function CardHeader({
  title,
  description,
  actions,
  headingLevel = 2,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  headingLevel?: 2 | 3
  className?: string
}) {
  const Heading = headingLevel === 2 ? 'h2' : 'h3'
  return (
    <div
      className={cn(
        'border-border flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4',
        className,
      )}
    >
      <div className="min-w-0">
        <Heading className="text-fg text-base font-semibold">{title}</Heading>
        {description ? <p className="text-muted mt-0.5 text-sm">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-5 py-4', className)} {...props} />
}
