import { useVirtualizer, useWindowVirtualizer, type Virtualizer } from '@tanstack/react-virtual'
import { useReducedMotion } from 'motion/react'
import { Play } from 'lucide-react'
import { memo, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

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
/** Rows after this many share one delay, so a long transcript re-forms quickly. */
const MORPH_STAGGER_ROWS = 24

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

/**
 * The line being spoken, filling in as playback passes it. Whisper times
 * segments, not words, so each word's moment is estimated by its position in
 * the line (character share of the segment's duration): a reading guide, not
 * a word-level alignment.
 */
function KaraokeText({ text, progress }: { text: string; progress: number }) {
  const total = text.length || 1
  // Each piece's share of the line: where it begins and ends, 0..1.
  const pieces = text
    .split(/(\s+)/)
    .reduce<{ part: string; begins: number; ends: number }[]>((list, part) => {
      const begins = list.at(-1)?.ends ?? 0
      list.push({ part, begins, ends: begins + part.length / total })
      return list
    }, [])
  return (
    <>
      {pieces.map(({ part, begins, ends }, index) => {
        if (part.trim() === '') return part
        const state = progress >= ends ? 'said' : progress >= begins ? 'saying' : 'ahead'
        return (
          <span
            key={index}
            className={cn(
              'transition-colors duration-150',
              state === 'said' && 'text-fg',
              state === 'saying' && 'text-accent',
              state === 'ahead' && 'text-faint',
            )}
          >
            {part}
          </span>
        )
      })}
    </>
  )
}

interface RowOptions {
  palette: SpeakerPalette
  query: string
  onSeek?: ((seconds: number) => void) | undefined
  /** Changes when the script is switched, so each line re-forms. 0 = no animation. */
  morphKey: number
}

const SegmentBody = memo(function SegmentBody({
  segment,
  index,
  progress,
  palette,
  query,
  onSeek,
  morphKey,
}: RowOptions & { segment: Segment; index: number; progress: number | null }) {
  const style = palette(segment.speaker)
  const clock = formatClock(segment.start)
  const active = progress !== null
  return (
    <div
      className={cn(
        'rounded-r-lg border-l-2 py-2 pr-3 pl-3 transition-[background-color,box-shadow,transform] duration-300',
        style.rule,
        active
          ? 'bg-accent-soft translate-x-1 shadow-[0_0_28px_-10px_var(--color-glow)]'
          : 'hover:bg-subtle',
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
        key={morphKey}
        className={cn(
          'text-fg leading-relaxed break-words',
          morphKey > 0 && 'animate-morph',
          active && 'text-lg font-medium',
        )}
        style={
          morphKey > 0
            ? { animationDelay: `${Math.min(index, MORPH_STAGGER_ROWS) * 22}ms` }
            : undefined
        }
        lang={textLang(segment.text, segment.language)}
      >
        {active && !query ? (
          <KaraokeText text={segment.text} progress={progress} />
        ) : (
          highlight(segment.text, query)
        )}
      </p>
    </div>
  )
})

function activeIndexAt(segments: Segment[], currentTime: number | null | undefined): number {
  if (currentTime == null) return -1
  return segments.findIndex((s) => currentTime >= s.start && currentTime < s.end)
}

function progressOf(segment: Segment, currentTime: number | null | undefined): number {
  const length = segment.end - segment.start
  if (currentTime == null || length <= 0) return 1
  return Math.min(1, Math.max(0, (currentTime - segment.start) / length))
}

interface ListProps extends RowOptions {
  segments: Segment[]
  currentTime?: number | null | undefined
  activeIndex: number
  follow: boolean
  label: string
}

function VirtualRows({
  virtualizer,
  offset,
  segments,
  currentTime,
  activeIndex,
  follow,
  label,
  ...row
}: ListProps & {
  virtualizer: Virtualizer<Window, Element> | Virtualizer<HTMLElement, Element>
  offset: number
}) {
  useEffect(() => {
    if (follow && activeIndex >= 0) virtualizer.scrollToIndex(activeIndex, { align: 'center' })
  }, [follow, activeIndex, virtualizer])
  return (
    <ol aria-label={label} className="relative" style={{ height: virtualizer.getTotalSize() }}>
      {virtualizer.getVirtualItems().map((item) => {
        const segment = segments[item.index]!
        const active = item.index === activeIndex
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
            <SegmentBody
              segment={segment}
              index={item.index}
              progress={active ? progressOf(segment, currentTime) : null}
              {...row}
            />
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

function PlainList({ segments, currentTime, activeIndex, follow, label, ...row }: ListProps) {
  const activeRow = useRef<HTMLLIElement>(null)
  const reduceMotion = useReducedMotion()
  useEffect(() => {
    if (follow && activeIndex >= 0) {
      activeRow.current?.scrollIntoView({
        block: 'center',
        behavior: reduceMotion ? 'auto' : 'smooth',
      })
    }
  }, [follow, activeIndex, reduceMotion])
  return (
    <ol aria-label={label} className="space-y-1.5">
      {segments.map((segment, index) => {
        const active = index === activeIndex
        return (
          <li
            key={`${index}-${segment.start}`}
            ref={active ? activeRow : undefined}
            aria-current={active ? 'true' : undefined}
            className="[contain-intrinsic-size:auto_4.5rem] [content-visibility:auto]"
          >
            <SegmentBody
              segment={segment}
              index={index}
              progress={active ? progressOf(segment, currentTime) : null}
              {...row}
            />
          </li>
        )
      })}
    </ol>
  )
}

export function Transcript({
  segments,
  palette,
  currentTime,
  query = '',
  onSeek,
  label = 'Transcript',
  scrollElement,
  follow = false,
  morphKey = 0,
}: {
  segments: Segment[]
  palette: SpeakerPalette
  currentTime?: number | null | undefined
  query?: string
  onSeek?: ((seconds: number) => void) | undefined
  label?: string
  /** The scrolling container, when it is not the page (undefined = the page). */
  scrollElement?: HTMLElement | null
  /** Keep the line being played in view. */
  follow?: boolean
  /** Bump to make every line re-form (after switching script). */
  morphKey?: number
}) {
  const activeIndex = activeIndexAt(segments, currentTime)
  const props: ListProps = {
    segments,
    palette,
    currentTime,
    activeIndex,
    follow,
    query,
    onSeek,
    label,
    morphKey,
  }
  if (segments.length > VIRTUALIZE_ABOVE) {
    return scrollElement === undefined ? (
      <WindowVirtualList {...props} />
    ) : (
      <ElementVirtualList {...props} scrollElement={scrollElement} />
    )
  }
  return <PlainList {...props} />
}
