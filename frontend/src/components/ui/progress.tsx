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
      <div aria-hidden className="bg-subtle h-2 w-full overflow-hidden rounded-full">
        <div
          className="bg-brand relative h-full w-full origin-left rounded-full shadow-[0_0_12px_var(--color-glow)] transition-transform duration-500 ease-out"
          style={{ transform: `scaleX(${fraction})` }}
        >
          {/* A light sweep while incomplete, so a slow stage still looks alive. */}
          {fraction < 1 ? (
            <span className="animate-shimmer absolute inset-0 rounded-full bg-[linear-gradient(90deg,transparent,rgb(255_255_255/0.45),transparent)] bg-[length:200%_100%]" />
          ) : null}
        </div>
      </div>
    </div>
  )
}
