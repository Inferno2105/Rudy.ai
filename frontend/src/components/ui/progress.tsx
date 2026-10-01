import { cn } from '../../lib/utils'

/** Native `<progress>`, styled: correct semantics for free, in every browser. */
export function Progress({
  value,
  max = 1,
  label,
  className,
}: {
  value: number
  max?: number
  label: string
  className?: string
}) {
  return (
    <progress
      value={value}
      max={max}
      aria-label={label}
      className={cn(
        'bg-subtle block h-1.5 w-full appearance-none overflow-hidden rounded-full border-0',
        '[&::-webkit-progress-bar]:bg-subtle [&::-webkit-progress-bar]:rounded-full',
        '[&::-webkit-progress-value]:bg-accent [&::-webkit-progress-value]:rounded-full [&::-webkit-progress-value]:transition-[width]',
        '[&::-moz-progress-bar]:bg-accent [&::-moz-progress-bar]:rounded-full',
        className,
      )}
    />
  )
}
