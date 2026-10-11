import { languageStyle } from '../lib/language'
import { speakerName, type SpeakerPalette } from '../lib/speakers'
import { cn } from '../lib/utils'

/** Animated equalizer bars: the brand mark. Decorative. */
export function Equalizer({ className, bars = 4 }: { className?: string; bars?: number }) {
  return (
    <span aria-hidden className={cn('flex h-4 items-end gap-[3px]', className)}>
      {Array.from({ length: bars }, (_, i) => (
        <span
          key={i}
          className="animate-eq h-full w-[3px] origin-bottom rounded-full bg-current"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  )
}

export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn('bg-cta glow grid size-8 place-items-center rounded-xl text-white', className)}
    >
      <Equalizer />
    </span>
  )
}

/**
 * A live waveform: bars that move while `active`, and settle when it stops.
 * Decorative (the recording state is announced in text elsewhere).
 */
export function Waveform({
  active,
  bars = 32,
  className,
}: {
  active: boolean
  bars?: number
  className?: string
}) {
  return (
    <div aria-hidden className={cn('flex h-16 items-center gap-1', className)}>
      {Array.from({ length: bars }, (_, i) => {
        // A fixed, uneven shape so the idle bars still read as a waveform.
        const rest = 0.2 + 0.6 * Math.abs(Math.sin(i * 1.7) * Math.cos(i * 0.6))
        return (
          <span
            key={i}
            className={cn(
              'bg-brand h-full flex-1 origin-center rounded-full transition-transform duration-500',
              active && 'animate-wave',
            )}
            style={{
              transform: active ? undefined : `scaleY(${rest * 0.5})`,
              animationDelay: `${(i % 8) * 0.09 + (i % 3) * 0.05}s`,
              animationDuration: `${0.9 + (i % 5) * 0.12}s`,
            }}
          />
        )
      })}
    </div>
  )
}

/** Speakers as overlapping coloured avatars, most-speaking first. */
export function AvatarStack({
  speakers,
  palette,
  max = 4,
}: {
  speakers: string[]
  palette: SpeakerPalette
  max?: number
}) {
  if (speakers.length === 0) return null
  const shown = speakers.slice(0, max)
  const hidden = speakers.length - shown.length
  const label = `${speakers.length} speaker${speakers.length === 1 ? '' : 's'}`
  return (
    <span className="flex items-center">
      <span className="sr-only">{label}</span>
      {shown.map((speaker, i) => (
        <span
          key={speaker}
          aria-hidden
          title={speakerName(speaker)}
          className={cn(
            'ring-canvas grid size-7 place-items-center rounded-full font-mono text-[10px] font-semibold text-white ring-2',
            i > 0 && '-ml-2',
          )}
          style={{ backgroundColor: palette(speaker).hex }}
        >
          {initials(speaker)}
        </span>
      ))}
      {hidden > 0 ? (
        <span
          aria-hidden
          className="bg-subtle text-muted ring-canvas -ml-2 grid size-7 place-items-center rounded-full text-[10px] font-semibold ring-2"
        >
          +{hidden}
        </span>
      ) : null}
    </span>
  )
}

function initials(label: string): string {
  // SPEAKER_00 -> S0, SPEAKER_G01 (a session-wide id) -> G1.
  const match = /^SPEAKER_([A-Z]?)0*(\d+)$/i.exec(label)
  if (!match) return label.slice(0, 2)
  return `${match[1] || 'S'}${match[2]}`.toUpperCase()
}

const LANGUAGE_BAR: Record<string, string> = {
  English: 'bg-blue-500',
  Hindi: 'bg-orange-500',
  'Code-Mixed': 'bg-purple-500',
}

/** Share of speech per language, as one stacked bar. */
export function LanguageMixBar({
  mix,
  className,
}: {
  mix: Record<string, number>
  className?: string
}) {
  const entries = Object.entries(mix).sort((a, b) => b[1] - a[1])
  if (entries.length === 0) return null
  const description = entries
    .map(
      ([language, share]) =>
        `${languageStyle(language)?.label ?? language} ${Math.round(share * 100)}%`,
    )
    .join(', ')
  return (
    <div className={cn('space-y-1.5', className)}>
      <p className="sr-only">Language mix: {description}</p>
      <div className="bg-subtle flex h-1.5 overflow-hidden rounded-full" aria-hidden>
        {entries.map(([language, share]) => (
          <span
            key={language}
            className={cn('h-full', LANGUAGE_BAR[language] ?? 'bg-faint')}
            style={{ width: `${share * 100}%` }}
          />
        ))}
      </div>
      <p className="text-faint flex flex-wrap gap-x-3 text-[11px]" aria-hidden>
        {entries.map(([language, share]) => (
          <span key={language} className="inline-flex items-center gap-1">
            <span className={cn('size-1.5 rounded-full', LANGUAGE_BAR[language] ?? 'bg-faint')} />
            {languageStyle(language)?.label ?? language} {Math.round(share * 100)}%
          </span>
        ))}
      </p>
    </div>
  )
}
