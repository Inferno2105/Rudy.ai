/** Display formatting. Presentation only: values are never recomputed here. */

/** Non-breaking space: keeps a number and its unit on one line. */
export const NBSP = '\u00a0'

const fixedFormats = new Map<number, Intl.NumberFormat>()

/** A number with exactly `digits` decimals, in the reader's locale. */
export function formatFixed(value: number, digits: number): string {
  let format = fixedFormats.get(digits)
  if (!format) {
    format = new Intl.NumberFormat(undefined, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })
    fixedFormats.set(digits, format)
  }
  return format.format(value)
}

/** A count with locale grouping (`12,345`). */
export function formatCount(value: number): string {
  return formatFixed(value, 0)
}

/** `1` → `1 segment`, `2` → `2 segments`. */
export function plural(count: number, noun: string, pluralNoun = `${noun}s`): string {
  return `${formatCount(count)} ${count === 1 ? noun : pluralNoun}`
}

/** `75.4` → `1:15`, `3725` → `1:02:05`. */
export function formatClock(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds))
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const pad = (n: number) => n.toString().padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

/** `75.4` → `1m 15s`, `12.3` → `12.3s`, `3725` → `1h 2m`. */
export function formatDuration(totalSeconds: number): string {
  if (totalSeconds > 0 && totalSeconds < 0.05) return '<0.1s'
  if (totalSeconds < 60) return `${formatFixed(totalSeconds, totalSeconds < 10 ? 1 : 0)}s`
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  const s = Math.round(totalSeconds % 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`
}

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

/** The backend writes local ISO timestamps without a zone (`2026-10-01T15:28:23`). */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : dateTime.format(date)
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${formatCount(bytes)}${NBSP}B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${formatFixed(value, value < 10 ? 1 : 0)}${NBSP}${units[unit]}`
}

/** Fixed decimals for metric values; `—` for absent ones. */
export function formatMetric(value: number | null | undefined, digits = 3): string {
  return value == null || Number.isNaN(value) ? '—' : formatFixed(value, digits)
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  return value == null || Number.isNaN(value) ? '—' : `${formatFixed(value, digits)}%`
}

export function shortHash(value: string | null | undefined, length = 8): string {
  return value ? value.slice(0, length) : '—'
}

export function basename(path: string | null | undefined): string | null {
  if (!path) return null
  const parts = path.split(/[\\/]/)
  return parts[parts.length - 1] || null
}

/** `test_hindi.wav` from a run's audio path, else a readable fallback. */
export function runTitle(run: {
  run_id: string
  mode: string
  audio_path?: string | null | undefined
}): string {
  const name = basename(run.audio_path)
  if (name) return name
  return run.mode === 'live' ? 'Live session' : run.run_id
}
