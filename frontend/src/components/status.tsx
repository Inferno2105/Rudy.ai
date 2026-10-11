import { CheckCircle2, CircleDashed, CircleSlash, Loader2, XCircle } from 'lucide-react'

import type { Job } from '../api/types'
import { languageStyle } from '../lib/language'
import type { DisplayStatus } from '../lib/stages'
import { speakerName, type SpeakerPalette } from '../lib/speakers'
import { cn } from '../lib/utils'
import { Badge, type Tone } from './ui/badge'

const RUN_STATUS: Record<string, { tone: Tone; label: string }> = {
  completed: { tone: 'success', label: 'Completed' },
  partial: { tone: 'warning', label: 'Partial' },
  failed: { tone: 'danger', label: 'Failed' },
}

export function RunStatusBadge({ status }: { status: string }) {
  const style = RUN_STATUS[status] ?? { tone: 'neutral' as Tone, label: status }
  return <Badge tone={style.tone}>{style.label}</Badge>
}

const JOB_STATE: Record<Job['state'], { tone: Tone; label: string }> = {
  queued: { tone: 'neutral', label: 'Queued' },
  running: { tone: 'accent', label: 'Running' },
  stopping: { tone: 'warning', label: 'Finishing' },
  finished: { tone: 'success', label: 'Finished' },
  failed: { tone: 'danger', label: 'Failed' },
}

export function JobStateBadge({ state }: { state: Job['state'] }) {
  const style = JOB_STATE[state]
  return <Badge tone={style.tone}>{style.label}</Badge>
}

export function OriginBadge({ origin }: { origin: string }) {
  return origin === 'real_audio' ? (
    <Badge tone="neutral">Real audio</Badge>
  ) : (
    <Badge tone="danger">
      {origin === 'synthetic' ? 'Synthetic' : origin}
      <span className="sr-only">: not from a real recording, never used for reported results</span>
    </Badge>
  )
}

export function ModeLabel({ mode }: { mode: string }) {
  return <span className="text-muted text-sm">{mode === 'live' ? 'Live' : 'Batch'}</span>
}

export function SpeakerChip({
  label,
  palette,
  className,
}: {
  label: string | null | undefined
  palette: SpeakerPalette
  className?: string
}) {
  const style = palette(label)
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset',
        style.chip,
        className,
      )}
    >
      <span className={cn('size-1.5 rounded-full', style.dot)} aria-hidden />
      {speakerName(label)}
    </span>
  )
}

export function LanguageBadge({ language }: { language: string | null | undefined }) {
  const style = languageStyle(language)
  if (!style) return null
  return (
    <span
      className={cn(
        'inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-semibold tracking-wide ring-1 ring-inset',
        style.className,
      )}
    >
      <span aria-hidden>{style.short}</span>
      <span className="sr-only">{style.label}</span>
    </span>
  )
}

/** Visible key for the short language codes used on transcript segments. */
export function LanguageLegend({ languages }: { languages: (string | null | undefined)[] }) {
  const present = [...new Set(languages.filter((l): l is string => Boolean(l)))].sort()
  if (present.length === 0) return null
  return (
    <p className="text-muted flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" aria-hidden>
      {present.map((language) => {
        const style = languageStyle(language)
        return style ? (
          <span key={language} className="inline-flex items-center gap-1.5">
            <LanguageBadge language={language} />
            <span>{style.label}</span>
          </span>
        ) : null
      })}
    </p>
  )
}

export function StageIcon({ status }: { status: DisplayStatus }) {
  switch (status) {
    case 'ok':
      return <CheckCircle2 className="text-success size-4" aria-hidden />
    case 'failed':
      return <XCircle className="text-danger size-4" aria-hidden />
    case 'skipped':
      return <CircleSlash className="text-warning size-4" aria-hidden />
    case 'running':
      return <Loader2 className="text-accent size-4 animate-spin" aria-hidden />
    default:
      return <CircleDashed className="text-faint size-4" aria-hidden />
  }
}
