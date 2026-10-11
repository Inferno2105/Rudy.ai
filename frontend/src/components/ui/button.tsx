import { Slot } from 'radix-ui'
import { forwardRef, type ButtonHTMLAttributes } from 'react'

import { cn } from '../../lib/utils'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

const VARIANTS: Record<Variant, string> = {
  // Brand gradient with a soft glow; brightens on hover, presses in on click.
  primary:
    'bg-cta text-white glow shadow-[inset_0_1px_0_0_rgb(255_255_255/0.25)] hover:brightness-110',
  secondary: 'glass text-fg hover:bg-subtle hover:border-strong-border',
  ghost: 'text-muted hover:bg-subtle hover:text-fg',
  danger:
    'bg-danger text-white shadow-[0_10px_30px_-12px_var(--color-danger)] hover:brightness-110 dark:text-canvas',
}

const SIZES: Record<Size, string> = {
  sm: 'h-8 gap-1.5 rounded-lg px-2.5 text-sm',
  md: 'h-10 gap-2 rounded-xl px-4 text-sm',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  /** Render the child element (e.g. a router Link) with button styling. */
  asChild?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', asChild = false, className, type, ...props },
  ref,
) {
  const Component = asChild ? Slot.Root : 'button'
  return (
    <Component
      ref={ref}
      type={asChild ? undefined : (type ?? 'button')}
      className={cn(
        'inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap select-none',
        'transition-[transform,filter,background-color,border-color,color,box-shadow] duration-200 active:scale-[0.97]',
        'disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    />
  )
})
