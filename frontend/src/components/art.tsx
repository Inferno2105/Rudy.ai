/**
 * Original vector illustrations for the app, drawn in the theme's colours
 * (they follow light and dark through CSS variables). All decorative: every
 * one is aria-hidden, and nothing on a page depends on them for meaning.
 */
import { useId } from 'react'

import { cn } from '../lib/utils'

/** A smooth horizontal wave as an SVG path, closed down to the bottom edge. */
function wavePath({
  width,
  height,
  base,
  amplitude,
  wavelength,
  phase = 0,
}: {
  width: number
  height: number
  base: number
  amplitude: number
  wavelength: number
  phase?: number
}): string {
  const step = 12
  let d = `M0 ${height} L0 ${base}`
  for (let x = 0; x <= width; x += step) {
    const y =
      base +
      amplitude * Math.sin((x / wavelength) * Math.PI * 2 + phase) +
      amplitude * 0.35 * Math.sin((x / (wavelength * 0.43)) * Math.PI * 2 + phase * 1.7)
    d += ` L${x} ${y.toFixed(1)}`
  }
  return `${d} L${width} ${height} Z`
}

/** Heights for an equalizer skyline: a smooth, uneven envelope. */
function barHeights(count: number, peak: number): number[] {
  return Array.from({ length: count }, (_, i) => {
    const t = i / (count - 1)
    const envelope = Math.sin(t * Math.PI) ** 0.8
    const ripple = 0.55 + 0.45 * Math.abs(Math.sin(i * 1.31) * Math.cos(i * 0.47))
    return Math.max(6, peak * envelope * ripple)
  })
}

function Bubble({
  x,
  y,
  text,
  lang,
  delay,
  tone,
}: {
  x: number
  y: number
  text: string
  lang: string
  delay: string
  tone: 'a' | 'b' | 'c'
}) {
  const width = text.length * 15 + 44
  const fill =
    tone === 'a'
      ? 'var(--color-accent)'
      : tone === 'b'
        ? 'var(--color-accent-2)'
        : 'var(--color-highlight)'
  return (
    <g className="animate-float" style={{ animationDelay: delay, transformBox: 'fill-box' }}>
      <rect
        x={x}
        y={y}
        width={width}
        height={52}
        rx={26}
        style={{ fill: 'var(--color-surface)', stroke: fill, strokeWidth: 2, fillOpacity: 0.92 }}
      />
      <path
        d={`M${x + 34} ${y + 50} l-8 16 l22 -16 z`}
        style={{
          fill: 'var(--color-surface)',
          stroke: fill,
          strokeWidth: 2,
          strokeLinejoin: 'round',
        }}
      />
      <circle cx={x + 24} cy={y + 26} r={6} style={{ fill }} />
      <text
        x={x + 38}
        y={y + 33}
        lang={lang}
        style={{
          fill: 'var(--color-fg)',
          fontFamily: 'var(--font-display)',
          fontSize: 20,
          fontWeight: 600,
        }}
      >
        {text}
      </text>
    </g>
  )
}

/**
 * The signature scene: a striped retro sun setting behind a sound-wave
 * skyline, layered waves in front, speech bubbles in three languages above.
 */
export function SunsetScene({
  className,
  bubbles = true,
}: {
  className?: string
  bubbles?: boolean
}) {
  const id = useId().replace(/:/g, '')
  const W = 1200
  const H = 640
  const sunY = 430
  const bars = barHeights(56, 190)
  const barWidth = 9
  const barGap = (W * 0.62) / bars.length
  const barStart = W * 0.19
  return (
    <svg
      aria-hidden
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="xMidYMax slice"
      className={cn('block h-full w-full', className)}
    >
      <defs>
        <radialGradient id={`${id}-sun`} cx="50%" cy="30%" r="75%">
          <stop offset="0%" style={{ stopColor: 'var(--color-highlight)' }} />
          <stop offset="55%" style={{ stopColor: 'var(--color-accent)' }} />
          <stop offset="100%" style={{ stopColor: 'var(--color-accent-2)' }} />
        </radialGradient>
        <radialGradient id={`${id}-halo`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" style={{ stopColor: 'var(--color-accent)', stopOpacity: 0.55 }} />
          <stop offset="100%" style={{ stopColor: 'var(--color-accent)', stopOpacity: 0 }} />
        </radialGradient>
        <linearGradient id={`${id}-bars`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" style={{ stopColor: 'var(--color-highlight)' }} />
          <stop offset="100%" style={{ stopColor: 'var(--color-accent-2)' }} />
        </linearGradient>
        <linearGradient id={`${id}-wave1`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" style={{ stopColor: 'var(--color-accent-2)', stopOpacity: 0.55 }} />
          <stop offset="100%" style={{ stopColor: 'var(--color-canvas)', stopOpacity: 1 }} />
        </linearGradient>
        <linearGradient id={`${id}-wave2`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" style={{ stopColor: 'var(--color-accent)', stopOpacity: 0.4 }} />
          <stop offset="100%" style={{ stopColor: 'var(--color-canvas)', stopOpacity: 1 }} />
        </linearGradient>
        {/* Retro sun: horizontal gaps that widen toward the horizon. */}
        <mask id={`${id}-stripes`}>
          <rect x="0" y="0" width={W} height={H} fill="white" />
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <rect
              key={i}
              x="0"
              y={sunY - 70 + i * 26}
              width={W}
              height={3 + i * 2.2}
              fill="black"
            />
          ))}
        </mask>
      </defs>

      <circle cx={W / 2} cy={sunY} r={330} fill={`url(#${id}-halo)`} />
      <circle cx={W / 2} cy={sunY} r={180} fill={`url(#${id}-sun)`} mask={`url(#${id}-stripes)`} />

      {/* Sound-wave skyline on the horizon. */}
      <g opacity={0.9}>
        {bars.map((height, i) => (
          <rect
            key={i}
            x={barStart + i * barGap}
            y={sunY + 20 - height / 2}
            width={barWidth}
            height={height}
            rx={barWidth / 2}
            fill={`url(#${id}-bars)`}
            opacity={0.35 + 0.65 * (height / 190)}
          />
        ))}
      </g>

      <path
        d={wavePath({ width: W, height: H, base: 500, amplitude: 22, wavelength: 520, phase: 0.6 })}
        fill={`url(#${id}-wave2)`}
      />
      <path
        d={wavePath({ width: W, height: H, base: 548, amplitude: 18, wavelength: 380, phase: 2.1 })}
        fill={`url(#${id}-wave1)`}
      />
      <path
        d={wavePath({ width: W, height: H, base: 596, amplitude: 12, wavelength: 300, phase: 4 })}
        style={{ fill: 'var(--color-canvas)' }}
      />

      {bubbles ? (
        // Bubbles need the full scene width; on narrow screens they would be cut off.
        <g className="max-sm:hidden">
          <Bubble x={170} y={392} text="नमस्ते सबको" lang="hi" delay="0s" tone="a" />
          <Bubble x={835} y={372} text="Let's begin" lang="en" delay="1.2s" tone="b" />
          <Bubble x={760} y={456} text="Kal tak ho jayega" lang="hi-Latn" delay="2.4s" tone="c" />
        </g>
      ) : null}
    </svg>
  )
}

/** Soft waves along the bottom of every app page. */
export function WaveBackdrop() {
  const id = useId().replace(/:/g, '')
  const W = 1600
  const H = 360
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-x-0 bottom-0 -z-10 h-[42vh] min-h-56 opacity-60"
    >
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full">
        <defs>
          <linearGradient id={`${id}-a`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" style={{ stopColor: 'var(--color-accent)', stopOpacity: 0.16 }} />
            <stop offset="100%" style={{ stopColor: 'var(--color-accent-2)', stopOpacity: 0.12 }} />
          </linearGradient>
          <linearGradient id={`${id}-b`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" style={{ stopColor: 'var(--color-accent-2)', stopOpacity: 0.1 }} />
            <stop
              offset="100%"
              style={{ stopColor: 'var(--color-highlight)', stopOpacity: 0.12 }}
            />
          </linearGradient>
        </defs>
        <path
          d={wavePath({ width: W, height: H, base: 150, amplitude: 34, wavelength: 700, phase: 1 })}
          fill={`url(#${id}-a)`}
        />
        <path
          d={wavePath({ width: W, height: H, base: 220, amplitude: 26, wavelength: 520, phase: 3 })}
          fill={`url(#${id}-b)`}
        />
      </svg>
    </div>
  )
}

/** A small decorative waveform line, used under section headings. */
export function WaveRule({ className }: { className?: string }) {
  const points = Array.from({ length: 60 }, (_, i) => {
    const x = i * 4
    const y = 10 + 7 * Math.sin(i * 0.55) * Math.sin(i * 0.11)
    return `${x},${y.toFixed(1)}`
  }).join(' ')
  return (
    <svg aria-hidden viewBox="0 0 240 20" className={cn('h-5 w-40', className)}>
      <polyline
        points={points}
        fill="none"
        style={{ stroke: 'var(--color-accent)' }}
        strokeWidth={2}
        strokeLinecap="round"
      />
    </svg>
  )
}
