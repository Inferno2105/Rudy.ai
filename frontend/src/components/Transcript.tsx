import { Play } from 'lucide-react'
import { memo, type ReactNode } from 'react'

import type { Segment } from '../api/types'
import { formatClock } from '../lib/format'
import { textLang } from '../lib/language'
import type { SpeakerPalette } from '../lib/speakers'
import { cn } from '../lib/utils'
import { LanguageBadge, SpeakerChip } from './status'

function highlight(text: string, query: string): ReactNode {
  if (!query) return text
  const lower = text.toLocaleLowerCase()
  const needle = query.toLocaleLowerCase()
  const parts: ReactNode[] = []
  let from = 0
  for (let at = lower.indexOf(needle); at !== -1; at = lower.indexOf(needle, from)) {
    if (at > from) parts.push(text.slice(from, at))
    parts.push(
      <mark key={at} className="text-fg rounded-sm bg-yellow-200 px-0.5 dark:bg-yellow-500/40">
        {text.slice(at, at + needle.length)}
      </mark>,
    )
    from = at + needle.length
  }
  if (from < text.length) parts.push(text.slice(from))
  return parts
}

interface SegmentRowProps {
  segment: Segment
  palette: SpeakerPalette
  active: boolean
  query: string
  onSeek?: ((seconds: number) => void) | undefined
}

const SegmentRow = memo(function SegmentRow({
  segment,
  palette,
  active,
  query,
  onSeek,
}: SegmentRowProps) {
  const style = palette(segment.speaker)
  const clock = formatClock(segment.start)
  return (
    <li
      className={cn(
        'rounded-r-lg border-l-2 py-2 pr-3 pl-3 transition-colors [contain-intrinsic-size:auto_4.5rem] [content-visibility:auto]',
        style.rule,
        active ? 'bg-accent-soft' : 'hover:bg-subtle/60',
      )}
      aria-current={active ? 'true' : undefined}
    >
      <div className="mb-1 flex flex-wrap items-center gap-2">
        {onSeek ? (
          <button
            type="button"
            onClick={() => onSeek(segment.start)}
            className="text-muted hover:text-accent inline-flex items-center gap-1 rounded font-mono text-xs tabular-nums"
            aria-label={`Play from ${clock}`}
          >
            <Play className="size-3" aria-hidden />
            {clock}
          </button>
        ) : (
          <span translate="no" className="text-muted font-mono text-xs tabular-nums">
            {clock}
          </span>
        )}
        <SpeakerChip label={segment.speaker} palette={palette} />
        <LanguageBadge language={segment.language} />
      </div>
      <p
        className="text-fg leading-relaxed break-words"
        lang={textLang(segment.text, segment.language)}
      >
        {highlight(segment.text, query)}
      </p>
    </li>
  )
})

export function Transcript({
  segments,
  palette,
  currentTime,
  query = '',
  onSeek,
  label = 'Transcript',
}: {
  segments: Segment[]
  palette: SpeakerPalette
  currentTime?: number | null | undefined
  query?: string
  onSeek?: ((seconds: number) => void) | undefined
  label?: string
}) {
  return (
    <ol aria-label={label} className="space-y-1.5">
      {segments.map((segment, index) => (
        <SegmentRow
          key={`${index}-${segment.start}`}
          segment={segment}
          palette={palette}
          query={query}
          onSeek={onSeek}
          active={currentTime != null && currentTime >= segment.start && currentTime < segment.end}
        />
      ))}
    </ol>
  )
}
