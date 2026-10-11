import { motion } from 'motion/react'
import { useMemo, type KeyboardEvent, type MouseEvent } from 'react'

import type { Segment } from '../api/types'
import { EASE_OUT } from '../lib/easing'
import { formatClock } from '../lib/format'
import { speakerName, type SpeakerPalette } from '../lib/speakers'

const KEY_STEP_SEC = 5

/**
 * Who spoke when, as a coloured ribbon across the whole meeting, with a
 * playhead. When `onSeek` is given it is a slider: click anywhere or use the
 * arrow keys (5 s steps), Home and End to move playback there.
 */
export function SpeakerTimeline({
  segments,
  palette,
  currentTime,
  onSeek,
}: {
  segments: Segment[]
  palette: SpeakerPalette
  currentTime?: number | null | undefined
  onSeek?: ((seconds: number) => void) | undefined
}) {
  const duration = useMemo(
    () => segments.reduce((max, segment) => Math.max(max, segment.end), 0),
    [segments],
  )
  if (duration <= 0) return null

  const time = Math.min(Math.max(currentTime ?? 0, 0), duration)
  const seekTo = (seconds: number) => onSeek?.(Math.min(Math.max(seconds, 0), duration))

  function onClick(event: MouseEvent<HTMLDivElement>) {
    const box = event.currentTarget.getBoundingClientRect()
    if (box.width > 0) seekTo(((event.clientX - box.left) / box.width) * duration)
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const moves: Record<string, number> = {
      ArrowRight: time + KEY_STEP_SEC,
      ArrowUp: time + KEY_STEP_SEC,
      ArrowLeft: time - KEY_STEP_SEC,
      ArrowDown: time - KEY_STEP_SEC,
      Home: 0,
      End: duration,
    }
    const target = moves[event.key]
    if (target === undefined) return
    event.preventDefault()
    seekTo(target)
  }

  const interactive = Boolean(onSeek)
  const sliderProps = interactive
    ? {
        role: 'slider' as const,
        tabIndex: 0,
        'aria-label': 'Meeting timeline: who spoke when. Use arrow keys to seek.',
        'aria-valuemin': 0,
        'aria-valuemax': Math.round(duration),
        'aria-valuenow': Math.round(time),
        'aria-valuetext': `${formatClock(time)} of ${formatClock(duration)}`,
        onClick,
        onKeyDown,
      }
    : { role: 'img' as const, 'aria-label': 'Meeting timeline: who spoke when' }

  return (
    <div>
      <div
        {...sliderProps}
        className="group bg-subtle ring-border relative h-9 cursor-pointer overflow-hidden rounded-lg ring-1 ring-inset"
      >
        <motion.div
          className="absolute inset-0"
          initial={{ clipPath: 'inset(0 100% 0 0)' }}
          animate={{ clipPath: 'inset(0 0% 0 0)' }}
          transition={{ duration: 0.9, ease: EASE_OUT }}
        >
          {segments.map((segment, index) => (
            <span
              key={`${index}-${segment.start}`}
              className="absolute inset-y-1 rounded-[3px] opacity-85 transition-opacity group-hover:opacity-100"
              style={{
                left: `${(segment.start / duration) * 100}%`,
                width: `max(2px, ${((segment.end - segment.start) / duration) * 100}%)`,
                backgroundColor: palette(segment.speaker).hex,
              }}
            />
          ))}
        </motion.div>
        {interactive ? (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-y-0 w-0.5 bg-white shadow-[0_0_10px_2px_var(--color-glow)] transition-[left] duration-200 ease-linear"
            style={{ left: `${(time / duration) * 100}%` }}
          />
        ) : null}
      </div>
      <div
        className="text-faint mt-1.5 flex justify-between font-mono text-[11px] tabular-nums"
        aria-hidden
      >
        <span>{formatClock(interactive ? time : 0)}</span>
        <span>{formatClock(duration)}</span>
      </div>
      <SpeakerLegend segments={segments} palette={palette} />
    </div>
  )
}

function SpeakerLegend({ segments, palette }: { segments: Segment[]; palette: SpeakerPalette }) {
  const shares = useMemo(() => {
    const totals = new Map<string, number>()
    for (const segment of segments) {
      const key = segment.speaker ?? 'UNKNOWN'
      totals.set(key, (totals.get(key) ?? 0) + Math.max(0, segment.end - segment.start))
    }
    return [...totals.entries()].sort((a, b) => b[1] - a[1])
  }, [segments])
  const speaking = shares.reduce((sum, [, seconds]) => sum + seconds, 0) || 1
  return (
    <ul
      className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs"
      aria-label="Speaking time on the timeline"
    >
      {shares.map(([speaker, seconds]) => (
        <li key={speaker} className="text-muted inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className="size-2 rounded-full"
            style={{ backgroundColor: palette(speaker).hex }}
          />
          {speakerName(speaker)}
          <span className="text-faint tabular-nums">{Math.round((seconds / speaking) * 100)}%</span>
        </li>
      ))}
    </ul>
  )
}
