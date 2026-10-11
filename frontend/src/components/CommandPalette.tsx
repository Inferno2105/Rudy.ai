/* oxlint-disable jsx-a11y/prefer-tag-over-role -- the WAI-ARIA combobox
   pattern: options with an icon and two lines of text cannot be native
   <select>/<option>s, so the listbox, its groups and options are divs. */
import {
  BarChart3,
  CornerDownLeft,
  FileAudio,
  ListMusic,
  MessageSquareQuote,
  Mic,
  Search,
  Upload,
} from 'lucide-react'
import { Dialog as DialogPrimitive } from 'radix-ui'
import { useEffect, useId, useMemo, useState, type KeyboardEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router'

import { useRuns, useSearch } from '../api/queries'
import type { RunSummary, SearchHit } from '../api/types'
import { basename, formatClock, formatDateTime } from '../lib/format'
import { speakerName } from '../lib/speakers'
import { cn } from '../lib/utils'

interface Item {
  id: string
  group: string
  icon: ReactNode
  title: ReactNode
  detail?: ReactNode
  to: string
  /** Plain text for the screen-reader announcement of the highlighted option. */
  label: string
}

const PAGES = [
  { to: '/meetings', label: 'Meetings', icon: <ListMusic />, keywords: 'home list runs' },
  { to: '/new', label: 'New run', icon: <Upload />, keywords: 'upload process recording' },
  { to: '/live', label: 'Live recording', icon: <Mic />, keywords: 'microphone record start' },
  { to: '/evaluation', label: 'Evaluation', icon: <BarChart3 />, keywords: 'metrics wer der' },
]

function meetingName(run: RunSummary): string {
  return basename(run.audio_path) ?? (run.mode === 'live' ? 'Live session' : run.run_id)
}

/** ``text`` with every case-insensitive occurrence of ``query`` marked. */
function Highlighted({ text, query }: { text: string; query: string }) {
  const needle = query.trim().toLocaleLowerCase()
  if (!needle) return <>{text}</>
  const parts: ReactNode[] = []
  const lower = text.toLocaleLowerCase()
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
  return <>{parts}</>
}

/** A line of context around the first match, so long segments stay readable. */
function excerpt(text: string, query: string, radius = 70): string {
  const at = text.toLocaleLowerCase().indexOf(query.trim().toLocaleLowerCase())
  if (at < 0 || text.length <= radius * 2) return text
  const start = Math.max(0, at - radius)
  const end = Math.min(text.length, at + query.length + radius)
  return `${start > 0 ? '…' : ''}${text.slice(start, end)}${end < text.length ? '…' : ''}`
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms)
    return () => window.clearTimeout(timer)
  }, [value, ms])
  return debounced
}

function PaletteBody({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const listId = useId()
  const [query, setQuery] = useState('')
  const [highlighted, setHighlighted] = useState(0)
  const searchFor = useDebounced(query, 180)
  const runs = useRuns({})
  const search = useSearch(searchFor)
  const q = query.trim().toLocaleLowerCase()

  const items = useMemo<Item[]>(() => {
    const pages = PAGES.filter(
      (page) => !q || `${page.label} ${page.keywords}`.toLocaleLowerCase().includes(q),
    ).map<Item>((page) => ({
      id: `page:${page.to}`,
      group: 'Go to',
      icon: page.icon,
      title: page.label,
      to: page.to,
      label: page.label,
    }))
    const meetings = (runs.data ?? [])
      .filter((run) => !q || meetingName(run).toLocaleLowerCase().includes(q))
      .slice(0, q ? 6 : 4)
      .map<Item>((run) => ({
        id: `run:${run.run_id}`,
        group: q ? 'Meetings' : 'Recent meetings',
        icon: <FileAudio />,
        title: <Highlighted text={meetingName(run)} query={query} />,
        detail: formatDateTime(run.created_at),
        to: `/runs/${encodeURIComponent(run.run_id)}`,
        label: `${meetingName(run)}, ${formatDateTime(run.created_at)}`,
      }))
    const lines =
      q.length >= 2 && searchFor.trim().toLocaleLowerCase() === q
        ? (search.data ?? []).map<Item>((hit: SearchHit) => ({
            id: `line:${hit.run_id}:${hit.idx}`,
            group: 'Said in a meeting',
            icon: <MessageSquareQuote />,
            title: <Highlighted text={excerpt(hit.text, query)} query={query} />,
            detail: (
              <>
                {basename(hit.audio_path) ?? (hit.mode === 'live' ? 'Live session' : hit.run_id)} ·{' '}
                {formatDateTime(hit.created_at)} · {speakerName(hit.speaker)} ·{' '}
                <span className="font-mono tabular-nums">{formatClock(hit.start ?? 0)}</span>
              </>
            ),
            to: `/runs/${encodeURIComponent(hit.run_id)}?t=${hit.start ?? 0}`,
            label: `${hit.text}, said by ${speakerName(hit.speaker)} at ${formatClock(hit.start ?? 0)}`,
          }))
        : []
    return [...pages, ...meetings, ...lines]
  }, [q, query, runs.data, search.data, searchFor])

  const active = Math.min(highlighted, Math.max(0, items.length - 1))
  const optionId = (index: number) => `${listId}-option-${index}`

  function choose(item: Item | undefined) {
    if (!item) return
    onClose()
    navigate(item.to)
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const step = event.key === 'ArrowDown' ? 1 : -1
      setHighlighted((active + step + items.length) % Math.max(1, items.length))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      choose(items[active])
    }
  }

  // Keep the highlighted option in view while moving through a long list.
  useEffect(() => {
    document.getElementById(optionId(active))?.scrollIntoView({ block: 'nearest' })
  })

  const groups: { name: string; entries: { item: Item; index: number }[] }[] = []
  items.forEach((item, index) => {
    const last = groups.at(-1)
    if (last?.name === item.group) last.entries.push({ item, index })
    else groups.push({ name: item.group, entries: [{ item, index }] })
  })
  const searching =
    q.length >= 2 && (search.isFetching || searchFor.trim().toLocaleLowerCase() !== q)

  return (
    <>
      <div className="border-border flex items-center gap-3 border-b px-4">
        <Search className="text-faint size-5 shrink-0" aria-hidden />
        <input
          role="combobox"
          aria-expanded
          aria-controls={listId}
          aria-activedescendant={items.length ? optionId(active) : undefined}
          aria-autocomplete="list"
          aria-label="Search meetings, transcripts and pages"
          placeholder="Search everything that was said…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setHighlighted(0)
          }}
          onKeyDown={onKeyDown}
          autoComplete="off"
          spellCheck={false}
          className="text-fg placeholder:text-faint h-14 flex-1 bg-transparent text-base outline-none"
        />
        <kbd className="text-faint border-border hidden rounded border px-1.5 py-0.5 font-mono text-[10px] sm:block">
          Esc
        </kbd>
      </div>

      <div
        id={listId}
        role="listbox"
        aria-label="Results"
        className="max-h-[60vh] overflow-y-auto p-2"
      >
        {groups.map(({ name, entries }, groupIndex) => (
          <div key={name} role="group" aria-labelledby={`${listId}-group-${groupIndex}`}>
            <div
              id={`${listId}-group-${groupIndex}`}
              className="text-faint px-3 pt-3 pb-1 text-[11px] font-semibold tracking-wide uppercase"
            >
              {name}
            </div>
            {entries.map(({ item, index }) => (
              <div
                key={item.id}
                id={optionId(index)}
                role="option"
                aria-selected={index === active}
                aria-label={item.label}
                tabIndex={-1}
                onMouseMove={() => setHighlighted(index)}
                onClick={() => choose(item)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') choose(item)
                }}
                className={cn(
                  'flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 transition-colors',
                  index === active ? 'bg-accent-soft' : 'hover:bg-subtle',
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    'grid size-8 shrink-0 place-items-center rounded-lg [&_svg]:size-4',
                    index === active ? 'bg-accent text-accent-fg' : 'bg-subtle text-muted',
                  )}
                >
                  {item.icon}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="text-fg line-clamp-2 block text-sm">{item.title}</span>
                  {item.detail ? (
                    <span className="text-faint block truncate text-xs">{item.detail}</span>
                  ) : null}
                </span>
                {index === active ? (
                  <CornerDownLeft className="text-faint size-4 shrink-0" aria-hidden />
                ) : null}
              </div>
            ))}
          </div>
        ))}
      </div>

      <output className="text-faint border-border block border-t px-4 py-2 text-xs">
        {searching
          ? 'Searching transcripts…'
          : q.length >= 2 && search.data?.length === 0
            ? `Nobody said “${query.trim()}” in your meetings.`
            : q.length < 2
              ? 'Type two or more letters to search every transcript.'
              : `${items.length} result${items.length === 1 ? '' : 's'}`}
      </output>
    </>
  )
}

/**
 * Ctrl+K (⌘K on a Mac) from anywhere in the app, or the search button in the
 * header: jump to a page, a meeting, or the exact moment something was said.
 */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  useEffect(() => {
    function onKey(event: globalThis.KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        onOpenChange(!open)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onOpenChange])

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="data-[state=open]:animate-fade-in data-[state=closed]:animate-fade-out fixed inset-0 z-40 bg-black/50 backdrop-blur-sm" />
        <DialogPrimitive.Content className="glass data-[state=open]:animate-enter data-[state=closed]:animate-leave fixed top-[12vh] left-1/2 z-50 w-[calc(100vw-2rem)] max-w-2xl -translate-x-1/2 overflow-hidden rounded-2xl shadow-2xl">
          <DialogPrimitive.Title className="sr-only">Search</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">
            Search pages, meetings and everything said in them. Use the arrow keys to move and Enter
            to open.
          </DialogPrimitive.Description>
          <PaletteBody onClose={() => onOpenChange(false)} />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
