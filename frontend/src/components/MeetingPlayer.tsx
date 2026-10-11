import { Pause, Play, RotateCcw, RotateCw } from 'lucide-react'
import { useReducedMotion } from 'motion/react'
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from 'react'

import { audioUrl } from '../api/client'
import { useWaveform } from '../api/queries'
import type { Segment } from '../api/types'
import { formatClock } from '../lib/format'
import type { SpeakerPalette } from '../lib/speakers'
import { cn } from '../lib/utils'
import { SpeakerLegend } from './SpeakerTimeline'

export interface MeetingPlayerHandle {
  /** Jump to ``seconds``; starts playback unless ``play`` is false. */
  seek: (seconds: number, options?: { play?: boolean }) => void
}

const RATES = [1, 1.25, 1.5, 2] as const
const KEY_STEP_SEC = 5
const SKIP_SEC = 10
const HEIGHT_PX = 64
/** How often the transcript hears the playback time (the canvas runs every frame). */
const REPORT_EVERY_MS = 100
/** Bars drawn from the transcript alone, until (or unless) the waveform arrives. */
const FALLBACK_BINS = 240

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) ||
    target.closest('[role="dialog"]') !== null
  )
}

/** The speaking segment at ``t`` (segments are in time order). */
function segmentAt(segments: Segment[], t: number): Segment | undefined {
  let lo = 0
  let hi = segments.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const segment = segments[mid]!
    if (t < segment.start) hi = mid - 1
    else if (t >= segment.end) lo = mid + 1
    else return segment
  }
  return undefined
}

/**
 * The meeting's recording as a waveform coloured by who is speaking, with a
 * playhead that runs at the display's frame rate. Click or drag the waveform
 * to scrub; arrow keys step 5 s. Anywhere on the page (outside text fields),
 * Space or K plays and pauses, J and L skip 10 s.
 */
export const MeetingPlayer = forwardRef<
  MeetingPlayerHandle,
  {
    runId: string
    segments: Segment[]
    palette: SpeakerPalette
    onTimeUpdate?: (seconds: number) => void
  }
>(function MeetingPlayer({ runId, segments, palette, onTimeUpdate }, ref) {
  const audio = useRef<HTMLAudioElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const track = useRef<HTMLDivElement>(null)
  const reduceMotion = useReducedMotion()

  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [mediaDuration, setMediaDuration] = useState<number | null>(null)
  const [rate, setRate] = useState<(typeof RATES)[number]>(1)
  const [unavailable, setUnavailable] = useState(false)

  const waveform = useWaveform(runId)
  const transcriptEnd = useMemo(
    () => segments.reduce((max, segment) => Math.max(max, segment.end), 0),
    [segments],
  )
  const duration = mediaDuration ?? waveform.data?.duration_sec ?? transcriptEnd

  // Bar heights: the real loudness envelope, or speech/silence from the
  // transcript while it loads (or if the recording cannot be decoded).
  const peaks = useMemo(() => {
    if (waveform.data?.peaks.length) return waveform.data.peaks
    return Array.from({ length: FALLBACK_BINS }, (_, i) =>
      segmentAt(segments, ((i + 0.5) / FALLBACK_BINS) * transcriptEnd) ? 0.55 : 0.08,
    )
  }, [waveform.data, segments, transcriptEnd])
  const barColors = useMemo(
    () =>
      peaks.map((_, i) => {
        const segment = segmentAt(segments, ((i + 0.5) / peaks.length) * duration)
        return segment ? palette(segment.speaker).hex : null
      }),
    [peaks, segments, duration, palette],
  )

  // Drawing state lives in refs: the canvas repaints every frame while
  // playing, without re-rendering React.
  const live = useRef({ time: 0, hover: null as number | null, appear: 1, lastReport: 0 })

  const draw = useCallback(() => {
    const element = canvas.current
    const box = track.current
    const context = element?.getContext('2d')
    if (!element || !box || !context) return
    const ratio = window.devicePixelRatio || 1
    const width = Math.max(1, Math.round(box.clientWidth * ratio))
    const height = Math.round(HEIGHT_PX * ratio)
    if (element.width !== width || element.height !== height) {
      element.width = width
      element.height = height
    }
    context.clearRect(0, 0, width, height)
    const styles = getComputedStyle(element)
    const faint = styles.color
    const accent = styles.getPropertyValue('--color-accent').trim() || '#f59e0b'
    const { time: now, hover, appear } = live.current
    const step = width / peaks.length
    const barWidth = Math.max(1, step * 0.62)
    const playedUpTo = duration > 0 ? now / duration : 0

    peaks.forEach((peak, i) => {
      const h = Math.max(2 * ratio, peak * height * 0.92 * appear)
      const x = i * step + (step - barWidth) / 2
      const played = (i + 0.5) / peaks.length <= playedUpTo
      const color = barColors[i]
      context.globalAlpha = color ? (played ? 1 : 0.38) : played ? 0.7 : 0.3
      context.fillStyle = color ?? faint
      context.beginPath()
      context.roundRect(x, (height - h) / 2, barWidth, h, barWidth / 2)
      context.fill()
    })
    context.globalAlpha = 1

    if (hover != null) {
      context.fillStyle = faint
      context.globalAlpha = 0.6
      context.fillRect(Math.round(hover * width), 0, ratio, height)
      context.globalAlpha = 1
    }
    const x = Math.round(playedUpTo * width)
    context.shadowColor = accent
    context.shadowBlur = 10 * ratio
    context.fillStyle = accent
    context.fillRect(x - ratio, 0, 2 * ratio, height)
    context.shadowBlur = 0
  }, [peaks, barColors, duration])

  const drawRef = useRef(draw)
  useEffect(() => {
    drawRef.current = draw
    draw()
  }, [draw])

  // Bars grow in when a new set of peaks arrives (not on every repaint).
  useEffect(() => {
    if (reduceMotion || peaks.length === 0) {
      live.current.appear = 1
      drawRef.current()
      return
    }
    let frame = 0
    const started = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / 700)
      live.current.appear = 1 - (1 - t) ** 3
      drawRef.current()
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [peaks, reduceMotion])

  // While playing: repaint every frame, report the time a few times a second.
  useEffect(() => {
    if (!playing) return
    let frame = 0
    const tick = (now: number) => {
      const element = audio.current
      if (element) {
        live.current.time = element.currentTime
        draw()
        if (now - live.current.lastReport >= REPORT_EVERY_MS) {
          live.current.lastReport = now
          setTime(element.currentTime)
          onTimeUpdate?.(element.currentTime)
        }
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, draw, onTimeUpdate])

  // Repaint when the size changes (the canvas is drawn in device pixels).
  useEffect(() => {
    const box = track.current
    if (!box) return
    const observer = new ResizeObserver(() => draw())
    observer.observe(box)
    return () => observer.disconnect()
  }, [draw])

  const syncTime = useCallback(() => {
    const element = audio.current
    if (!element) return
    live.current.time = element.currentTime
    setTime(element.currentTime)
    onTimeUpdate?.(element.currentTime)
    draw()
  }, [draw, onTimeUpdate])

  const seekTo = useCallback(
    (seconds: number, play?: boolean) => {
      const element = audio.current
      if (!element) return
      element.currentTime = Math.min(Math.max(seconds, 0), duration || seconds)
      syncTime()
      if (play) {
        void element.play().catch(() => {
          // Autoplay can be refused; the position is still set.
        })
      }
    },
    [duration, syncTime],
  )

  const toggle = useCallback(() => {
    const element = audio.current
    if (!element) return
    if (element.paused) {
      void element.play().catch(() => {
        // Refused (no user gesture yet): stays paused.
      })
    } else element.pause()
  }, [])

  useImperativeHandle(ref, () => ({
    seek: (seconds, options) => seekTo(seconds, options?.play ?? true),
  }))

  // Media-player shortcuts, page-wide, but never while typing.
  useEffect(() => {
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) return
      const element = audio.current
      if (!element) return
      const onControl =
        event.target instanceof HTMLElement && event.target.closest('button, a, [role="slider"]')
      if ((event.key === ' ' && !onControl) || event.key === 'k') {
        event.preventDefault()
        toggle()
      } else if (event.key === 'j') seekTo(element.currentTime - SKIP_SEC, !element.paused)
      else if (event.key === 'l') seekTo(element.currentTime + SKIP_SEC, !element.paused)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [seekTo, toggle])

  function positionAt(clientX: number): number {
    const box = track.current?.getBoundingClientRect()
    if (!box || box.width <= 0) return 0
    return Math.min(1, Math.max(0, (clientX - box.left) / box.width))
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    live.current.hover = positionAt(event.clientX)
    draw()
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    const now = audio.current?.currentTime ?? time
    const moves: Record<string, number> = {
      ArrowRight: now + KEY_STEP_SEC,
      ArrowUp: now + KEY_STEP_SEC,
      ArrowLeft: now - KEY_STEP_SEC,
      ArrowDown: now - KEY_STEP_SEC,
      Home: 0,
      End: duration,
    }
    const target = moves[event.key]
    if (target === undefined) return
    event.preventDefault()
    seekTo(target, !audio.current?.paused)
  }

  const shownTime = Math.min(time, duration || time)

  return (
    <div>
      {/* The transcript below is the recording's text alternative. */}
      {/* oxlint-disable-next-line jsx-a11y/media-has-caption */}
      <audio
        ref={audio}
        src={audioUrl(runId)}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => {
          setPlaying(false)
          syncTime()
        }}
        onEnded={() => setPlaying(false)}
        onSeeked={syncTime}
        onLoadedMetadata={(event) => {
          const seconds = event.currentTarget.duration
          if (Number.isFinite(seconds)) setMediaDuration(seconds)
        }}
        onError={() => setUnavailable(true)}
      />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <button
          type="button"
          onClick={toggle}
          disabled={unavailable}
          aria-label={playing ? 'Pause' : 'Play'}
          className={cn(
            'relative grid size-12 shrink-0 place-items-center rounded-full bg-gradient-to-br from-[var(--color-cta-1)] to-[var(--color-cta-2)] text-[var(--color-cta-fg)] shadow-lg transition-transform hover:scale-105 active:scale-95 disabled:opacity-40',
            playing && 'animate-breathe',
          )}
        >
          {playing ? (
            <Pause className="size-5" aria-hidden />
          ) : (
            <Play className="ml-0.5 size-5" aria-hidden />
          )}
        </button>

        <div className="min-w-0 flex-1">
          <div
            ref={track}
            onPointerMove={onPointerMove}
            onPointerLeave={() => {
              live.current.hover = null
              draw()
            }}
            className="text-faint has-[:focus-visible]:outline-ring relative rounded-lg outline-offset-2 has-[:focus-visible]:outline-2"
            style={{ height: HEIGHT_PX }}
          >
            <canvas ref={canvas} aria-hidden className="text-faint absolute inset-0 size-full" />
            {/* The waveform is drawn on the canvas; this native range input on
                top of it is the actual control (click, drag, keys, AT). */}
            <input
              type="range"
              min={0}
              max={duration || 0}
              step={0.1}
              value={shownTime}
              disabled={unavailable}
              onChange={(event) =>
                seekTo(Number(event.currentTarget.value), !audio.current?.paused)
              }
              onKeyDown={onKeyDown}
              aria-label="Recording position. Arrow keys move 5 seconds."
              aria-valuetext={`${formatClock(shownTime)} of ${formatClock(duration)}`}
              className="absolute inset-0 size-full cursor-pointer opacity-0"
            />
          </div>
          <div className="text-faint mt-1 flex items-center justify-between gap-2 font-mono text-[11px] tabular-nums">
            <span translate="no">
              {formatClock(shownTime)} / {formatClock(duration)}
            </span>
            <span className="hidden sm:inline" aria-hidden>
              Space play · J/L ±10 s
            </span>
          </div>
        </div>

        {/* Beside the waveform on wide screens; their own row on a phone. */}
        <div className="order-last flex w-full shrink-0 items-center justify-end gap-1 sm:order-none sm:w-auto">
          <button
            type="button"
            onClick={() => seekTo((audio.current?.currentTime ?? 0) - SKIP_SEC, playing)}
            className="text-muted hover:text-fg hover:bg-subtle rounded-full p-2"
            aria-label="Back 10 seconds"
          >
            <RotateCcw className="size-4" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => seekTo((audio.current?.currentTime ?? 0) + SKIP_SEC, playing)}
            className="text-muted hover:text-fg hover:bg-subtle rounded-full p-2"
            aria-label="Forward 10 seconds"
          >
            <RotateCw className="size-4" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => {
              const next = RATES[(RATES.indexOf(rate) + 1) % RATES.length]!
              setRate(next)
              if (audio.current) audio.current.playbackRate = next
            }}
            className="text-muted hover:text-fg hover:bg-subtle min-w-12 rounded-full px-2 py-1.5 font-mono text-xs tabular-nums"
            aria-label={`Playback speed ${rate}×. Change speed`}
          >
            {rate}×
          </button>
        </div>
      </div>
      {unavailable ? (
        <p className="text-muted mt-2 text-xs">
          The recording is not available on this server, so playback is off. The transcript is
          unaffected.
        </p>
      ) : null}
      <SpeakerLegend segments={segments} palette={palette} />
    </div>
  )
})
