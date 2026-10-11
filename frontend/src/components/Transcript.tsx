import { useVirtualizer, useWindowVirtualizer, type Virtualizer } from '@tanstack/react-virtual'
import { Play } from 'lucide-react'
import { memo, useCallback, useState, type ReactNode } from 'react'

import type { Segment } from '../api/types'
import { formatClock } from '../lib/format'
import { textLang } from '../lib/language'
import type { SpeakerPalette } from '../lib/speakers'
import { cn } from '../lib/utils'
import { LanguageBadge, SpeakerChip } from './status'

/**
 * Above this many segments only the rows near the viewport are rendered. A
 * one-hour meeting runs to several hundred segments; below the threshold the
 * plain list is kept, because it costs nothing and the browser's own
 * find-in-page then sees every line.
 */
export const VIRTUALIZE_ABOVE = 150
const ESTIMATED_ROW_PX = 76

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

interface RowOptions {
  palette: SpeakerPalette
  query: string
  onSeek?: ((seconds: number) => void) | undefined
}

const SegmentBody = memo(function SegmentBody({
  segment,
  active,
  palette,
  query,
  onSeek,
}: RowOptions & { segment: Segment; active: boolean }) {
  const style = palette(segment.speaker)
  const clock = formatClock(segment.start)
  return (
    <div
      className={cn(
        'rounded-r-lg border-l-2 py-2 pr-3 pl-3 transition-colors',
        style.rule,
        active ? 'bg-accent-soft shadow-[0_0_28px_-10px_var(--color-glow)]' : 'hover:bg-subtle',
      )}
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
    </div>
  )
})

function isActive(segment: Segment, currentTime: number | null | undefined): boolean {
  return currentTime != null && currentTime >= segment.start && currentTime < segment.end
}

interface ListProps extends RowOptions {
  segments: Segment[]
  currentTime?: number | null | undefined
  label: string
}

function VirtualRows({
  virtualizer,
  offset,
  segments,
  currentTime,
  label,
  ...row
}: ListProps & {
  virtualizer: Virtualizer<Window, Element> | Virtualizer<HTMLElement, Element>
  offset: number
}) {
  return (
    <ol aria-label={label} className="relative" style={{ height: virtualizer.getTotalSize() }}>
      {virtualizer.getVirtualItems().map((item) => {
        const segment = segments[item.index]!
        const active = isActive(segment, currentTime)
        return (
          <li
            key={item.key}
            ref={virtualizer.measureElement}
            data-index={item.index}
            aria-setsize={segments.length}
            aria-posinset={item.index + 1}
            aria-current={active ? 'true' : undefined}
            className="absolute top-0 left-0 w-full pb-1.5"
            style={{ transform: `translateY(${item.start - offset}px)` }}
          >
            <SegmentBody segment={segment} active={active} {...row} />
          </li>
        )
      })}
    </ol>
  )
}

/** Rows scrolled by the page itself (the run page). */
function WindowVirtualList(props: ListProps) {
  // The list's distance from the top of the document, measured when it
  // mounts (in a ref callback, never during render).
  const [offset, setOffset] = useState(0)
  const measure = useCallback((node: HTMLDivElement | null) => {
    if (node) setOffset(node.getBoundingClientRect().top + window.scrollY)
  }, [])
  // The incompatible-library rule only matters under the React Compiler, which
  // this project does not use; TanStack Virtual is used as documented.
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useWindowVirtualizer({
    count: props.segments.length,
    estimateSize: () => ESTIMATED_ROW_PX,
    overscan: 10,
    // React 19: let React batch the virtualizer's updates instead of forcing
    // synchronous re-renders from inside its measurement callbacks.
    useFlushSync: false,
    scrollMargin: offset,
  })
  return (
    <div ref={measure}>
      <VirtualRows {...props} virtualizer={virtualizer} offset={offset} />
    </div>
  )
}

/** Rows inside their own scrolling container (the live view). */
function ElementVirtualList({
  scrollElement,
  ...props
}: ListProps & { scrollElement: HTMLElement | null }) {
  // The incompatible-library rule only matters under the React Compiler, which
  // this project does not use; TanStack Virtual is used as documented.
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: props.segments.length,
    getScrollElement: () => scrollElement,
    estimateSize: () => ESTIMATED_ROW_PX,
    overscan: 10,
    // React 19: let React batch the virtualizer's updates instead of forcing
    // synchronous re-renders from inside its measurement callbacks.
    useFlushSync: false,
  })
  return <VirtualRows {...props} virtualizer={virtualizer} offset={0} />
}

export function Transcript({
  segments,
  palette,
  currentTime,
  query = '',
  onSeek,
  label = 'Transcript',
  scrollElement,
}: {
  segments: Segment[]
  palette: SpeakerPalette
  currentTime?: number | null | undefined
  query?: string
  onSeek?: ((seconds: number) => void) | undefined
  label?: string
  /** The scrolling container, when it is not the page (undefined = the page). */
  scrollElement?: HTMLElement | null
}) {
  const props: ListProps = { segments, palette, currentTime, query, onSeek, label }
  if (segments.length > VIRTUALIZE_ABOVE) {
    return scrollElement === undefined ? (
      <WindowVirtualList {...props} />
    ) : (
      <ElementVirtualList {...props} scrollElement={scrollElement} />
    )
  }
  return (
    <ol aria-label={label} className="space-y-1.5">
      {segments.map((segment, index) => {
        const active = isActive(segment, currentTime)
        return (
          <li
            key={`${index}-${segment.start}`}
            aria-current={active ? 'true' : undefined}
            className="[contain-intrinsic-size:auto_4.5rem] [content-visibility:auto]"
          >
            <SegmentBody
              segment={segment}
              active={active}
              palette={palette}
              query={query}
              onSeek={onSeek}
            />
          </li>
        )
      })}
    </ol>
  )
}
