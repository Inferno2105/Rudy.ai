import type { HTMLAttributes, ReactNode } from 'react'

import { cn } from '../../lib/utils'

/** A glass panel. `interactive` adds a hover lift for cards that are links. */
export function Card({
  className,
  interactive = false,
  ...props
}: HTMLAttributes<HTMLElement> & { interactive?: boolean }) {
  return (
    <section
      className={cn(
        'glass rounded-2xl',
        interactive &&
          'hover:border-strong-border transition-[transform,box-shadow,border-color] duration-300 hover:-translate-y-0.5 hover:shadow-[0_24px_48px_-24px_var(--color-glow)]',
        className,
      )}
      {...props}
    />
  )
}

export function CardHeader({
  title,
  description,
  actions,
  headingLevel = 2,
  icon,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  headingLevel?: 2 | 3
  icon?: ReactNode
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
      <div className="flex min-w-0 items-start gap-3">
        {icon ? <IconChip>{icon}</IconChip> : null}
        <div className="min-w-0">
          <Heading className="text-fg text-base font-semibold">{title}</Heading>
          {description ? <p className="text-muted mt-0.5 text-sm">{description}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-5 py-4', className)} {...props} />
}

/** A small gradient-tinted square holding an icon. Decorative. */
export function IconChip({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        'bg-accent-soft text-accent ring-accent/20 grid size-8 shrink-0 place-items-center rounded-lg ring-1 ring-inset [&_svg]:size-4',
        className,
      )}
    >
      {children}
    </span>
  )
}
