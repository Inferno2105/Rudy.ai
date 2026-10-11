import { cn } from '../../lib/utils'

/**
 * A progress bar. The semantics come from a native `<progress>` (announced by
 * assistive technology); the visible bar is drawn separately and scaled with
 * `transform`, which animates on the compositor instead of re-laying out the
 * page on every update the way animating `width` would.
 */
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
  const fraction = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0
  return (
    <div className={cn('relative', className)}>
      <progress value={value} max={max} aria-label={label} className="sr-only" />
      <div aria-hidden className="bg-subtle h-1.5 w-full overflow-hidden rounded-full">
        <div
          className="bg-accent h-full w-full origin-left rounded-full transition-transform duration-300"
          style={{ transform: `scaleX(${fraction})` }}
        />
      </div>
    </div>
  )
}
