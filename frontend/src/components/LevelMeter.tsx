import { LEVEL_HISTORY } from '../api/useMicLevel'
import { CLIPPING, QUIET } from '../lib/level'
import { cn } from '../lib/utils'

/**
 * The microphone's loudness as a row of bars, newest on the right; the row
 * scrolls left as readings arrive. Real input from the server's microphone,
 * not an animation.
 */
export function LevelMeter({ history, className }: { history: number[]; className?: string }) {
  const bars = Array.from(
    { length: LEVEL_HISTORY },
    (_, i) => history[history.length - LEVEL_HISTORY + i] ?? 0,
  )
  const current = history.at(-1) ?? 0
  return (
    <div className={className}>
      <meter
        className="sr-only"
        min={0}
        max={1}
        low={QUIET}
        high={CLIPPING}
        optimum={0.5}
        value={current}
        aria-label="Microphone level"
      />
      <div aria-hidden className="flex h-16 items-center gap-[3px]">
        {bars.map((level, i) => (
          <span
            // Bars are positions, not readings: the values shift through them.
            key={i}
            className={cn(
              'h-full flex-1 origin-center rounded-full transition-transform duration-100 ease-out motion-reduce:transition-none',
              level >= CLIPPING ? 'bg-danger' : 'bg-brand',
            )}
            style={{ transform: `scaleY(${Math.max(0.05, level)})` }}
          />
        ))}
      </div>
    </div>
  )
}
