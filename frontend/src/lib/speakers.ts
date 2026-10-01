/**
 * Speaker colours. Assigned by sorted label so a speaker keeps one colour
 * across the transcript, the chart and the table of the same run. Colour is
 * never the only cue: every place a colour appears also shows the label.
 */

export interface SpeakerStyle {
  /** Chip / badge classes (both themes). */
  chip: string
  /** Small solid marker. */
  dot: string
  /** Left rule on transcript turns. */
  rule: string
  /** Literal colour for charts. */
  hex: string
}

const PALETTE: SpeakerStyle[] = [
  {
    chip: 'bg-sky-50 text-sky-800 ring-sky-200 dark:bg-sky-950 dark:text-sky-200 dark:ring-sky-800',
    dot: 'bg-sky-500',
    rule: 'border-sky-400 dark:border-sky-600',
    hex: '#0ea5e9',
  },
  {
    chip: 'bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:ring-amber-800',
    dot: 'bg-amber-500',
    rule: 'border-amber-400 dark:border-amber-600',
    hex: '#f59e0b',
  },
  {
    chip: 'bg-emerald-50 text-emerald-800 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:ring-emerald-800',
    dot: 'bg-emerald-500',
    rule: 'border-emerald-400 dark:border-emerald-600',
    hex: '#10b981',
  },
  {
    chip: 'bg-fuchsia-50 text-fuchsia-800 ring-fuchsia-200 dark:bg-fuchsia-950 dark:text-fuchsia-200 dark:ring-fuchsia-800',
    dot: 'bg-fuchsia-500',
    rule: 'border-fuchsia-400 dark:border-fuchsia-600',
    hex: '#d946ef',
  },
  {
    chip: 'bg-orange-50 text-orange-900 ring-orange-200 dark:bg-orange-950 dark:text-orange-200 dark:ring-orange-800',
    dot: 'bg-orange-500',
    rule: 'border-orange-400 dark:border-orange-600',
    hex: '#f97316',
  },
  {
    chip: 'bg-teal-50 text-teal-800 ring-teal-200 dark:bg-teal-950 dark:text-teal-200 dark:ring-teal-800',
    dot: 'bg-teal-500',
    rule: 'border-teal-400 dark:border-teal-600',
    hex: '#14b8a6',
  },
  {
    chip: 'bg-rose-50 text-rose-800 ring-rose-200 dark:bg-rose-950 dark:text-rose-200 dark:ring-rose-800',
    dot: 'bg-rose-500',
    rule: 'border-rose-400 dark:border-rose-600',
    hex: '#f43f5e',
  },
  {
    chip: 'bg-violet-50 text-violet-800 ring-violet-200 dark:bg-violet-950 dark:text-violet-200 dark:ring-violet-800',
    dot: 'bg-violet-500',
    rule: 'border-violet-400 dark:border-violet-600',
    hex: '#8b5cf6',
  },
]

const UNKNOWN: SpeakerStyle = {
  chip: 'bg-subtle text-muted ring-border',
  dot: 'bg-faint',
  rule: 'border-strong-border',
  hex: '#94a3b8',
}

export function isUnknownSpeaker(label: string | null | undefined): boolean {
  return !label || label.toUpperCase() === 'UNKNOWN'
}

export type SpeakerPalette = (label: string | null | undefined) => SpeakerStyle

/** A palette for one run's speakers. */
export function speakerPalette(labels: Iterable<string | null | undefined>): SpeakerPalette {
  const known = [...new Set([...labels].filter((l): l is string => !isUnknownSpeaker(l)))].sort()
  const index = new Map(known.map((label, i) => [label, i]))
  return (label) => {
    if (isUnknownSpeaker(label)) return UNKNOWN
    const i = index.get(label as string)
    return i === undefined ? UNKNOWN : PALETTE[i % PALETTE.length]!
  }
}

/** `SPEAKER_00` → `Speaker 00`, `SPEAKER_G01` → `Speaker G01`. */
export function speakerName(label: string | null | undefined): string {
  if (isUnknownSpeaker(label)) return 'Unknown speaker'
  const match = /^SPEAKER_(.+)$/i.exec(label as string)
  return match ? `Speaker ${match[1]}` : (label as string)
}
