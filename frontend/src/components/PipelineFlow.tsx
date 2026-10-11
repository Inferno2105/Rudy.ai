import { Cpu, Gauge, Hash, Timer, Zap } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useState, type ReactNode } from 'react'

import type { RunDetail, StageInfo } from '../api/types'
import { EASE_OUT } from '../lib/easing'
import { formatClock, formatDuration, formatFixed } from '../lib/format'
import { buildStageRows, STAGE_STATUS_TEXT, stageLabel, type DisplayStatus } from '../lib/stages'
import { cn } from '../lib/utils'

/*
 * The batch pipeline as the graph it really is: Whisper and pyannote both read
 * the recording, alignment joins them, and the language-model stages hang off
 * the tagged transcript. Drawn in a fixed 1000 x 270 coordinate space; nodes
 * are HTML (positioned in %), edges an SVG underneath, so it scales as one.
 */
const W = 1000
const H = 270
const NODE_W = 122
const NODE_H = 66
const COLUMN = 146
const LANE = { top: 14, mid: 102, bottom: 190 } as const

interface NodeSpec {
  id: string
  title: string
  engine: (settings: Record<string, unknown>) => string
  col: number
  lane: keyof typeof LANE
}

const device = (value: unknown) => (value === 'cuda' ? 'GPU' : 'CPU')

const NODES: NodeSpec[] = [
  { id: 'audio', title: 'Recording', engine: () => 'source audio', col: 0, lane: 'mid' },
  {
    id: 'transcript',
    title: 'Transcribe',
    engine: (s) => `${String(s.whisper_model_size ?? 'Whisper')} · ${device(s.whisper_device)}`,
    col: 1,
    lane: 'top',
  },
  {
    id: 'diarization',
    title: 'Who spoke',
    engine: (s) => `pyannote · ${device(s.diarization_device)}`,
    col: 1,
    lane: 'bottom',
  },
  { id: 'aligned', title: 'Align', engine: () => 'words ↔ speakers', col: 2, lane: 'mid' },
  { id: 'merged', title: 'Merge turns', engine: () => 'speaker turns', col: 3, lane: 'mid' },
  { id: 'tagged', title: 'Language', engine: () => 'Hindi · English · mix', col: 4, lane: 'mid' },
  {
    id: 'hinglish',
    title: 'Hinglish',
    engine: (s) => String(s.ollama_model ?? 'LLM'),
    col: 5,
    lane: 'top',
  },
  { id: 'speaker_stats', title: 'Talk time', engine: () => 'statistics', col: 5, lane: 'mid' },
  {
    id: 'metadata',
    title: 'Metadata',
    engine: () => 'duration · languages',
    col: 5,
    lane: 'bottom',
  },
  {
    id: 'summary',
    title: 'Summary',
    engine: (s) => String(s.ollama_model ?? 'LLM'),
    col: 6,
    lane: 'top',
  },
  {
    id: 'action_items',
    title: 'Action items',
    engine: (s) => String(s.ollama_model ?? 'LLM'),
    col: 6,
    lane: 'mid',
  },
]

const EDGES: [string, string][] = [
  ['audio', 'transcript'],
  ['audio', 'diarization'],
  ['transcript', 'aligned'],
  ['diarization', 'aligned'],
  ['aligned', 'merged'],
  ['merged', 'tagged'],
  ['tagged', 'hinglish'],
  ['tagged', 'speaker_stats'],
  ['tagged', 'metadata'],
  ['hinglish', 'summary'],
  ['hinglish', 'action_items'],
]

const BY_ID = new Map(NODES.map((node) => [node.id, node]))

function origin(node: NodeSpec) {
  return { x: node.col * COLUMN, y: LANE[node.lane] }
}

function edgePath(from: NodeSpec, to: NodeSpec): string {
  const a = origin(from)
  const b = origin(to)
  const x1 = a.x + NODE_W
  const y1 = a.y + NODE_H / 2
  const x2 = b.x
  const y2 = b.y + NODE_H / 2
  const mid = (x1 + x2) / 2
  return `M${x1} ${y1} C${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`
}

/** Seconds since this view first saw the stage running (the manifest records ends, not starts). */
function RunningClock() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const started = Date.now()
    const timer = window.setInterval(() => setSeconds((Date.now() - started) / 1000), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return <span className="tabular-nums">{formatClock(seconds)}</span>
}

const NODE_TONE: Record<string, string> = {
  ok: 'border-accent/45 bg-surface',
  running: 'border-accent bg-accent-soft animate-breathe',
  failed: 'border-danger/70 bg-surface',
  skipped: 'border-dashed border-border bg-surface/60',
  pending: 'border-dashed border-border bg-surface/40',
}

function Node({
  spec,
  status,
  seconds,
  settings,
  index,
}: {
  spec: NodeSpec
  status: DisplayStatus
  seconds: number | undefined
  settings: Record<string, unknown>
  index: number
}) {
  const { x, y } = origin(spec)
  return (
    <motion.li
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.4, delay: index * 0.05, ease: EASE_OUT }}
      className={cn(
        'absolute flex flex-col justify-center rounded-xl border px-2.5 py-1.5 shadow-sm',
        NODE_TONE[status] ?? NODE_TONE.pending,
      )}
      style={{
        left: `${(x / W) * 100}%`,
        top: `${(y / H) * 100}%`,
        width: `${(NODE_W / W) * 100}%`,
        height: `${(NODE_H / H) * 100}%`,
      }}
    >
      <span
        className={cn(
          'truncate text-[13px] leading-tight font-semibold',
          status === 'pending' ? 'text-faint' : 'text-fg',
        )}
      >
        {spec.title}
        <span className="sr-only">
          {' '}
          ({stageLabel(spec.id)}): {STAGE_STATUS_TEXT[status] ?? status}
        </span>
      </span>
      <span className="text-muted truncate text-[11px] leading-tight">{spec.engine(settings)}</span>
      <span
        aria-hidden
        className={cn(
          'mt-0.5 truncate font-mono text-[11px] leading-tight',
          status === 'failed' ? 'text-danger' : status === 'running' ? 'text-accent' : 'text-faint',
        )}
      >
        {status === 'running' ? (
          <>
            working · <RunningClock />
          </>
        ) : status === 'ok' && seconds != null ? (
          formatDuration(seconds)
        ) : spec.id === 'audio' ? (
          'input'
        ) : (
          (STAGE_STATUS_TEXT[status] ?? status)
        )}
      </span>
    </motion.li>
  )
}

function Chip({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <span className="glass text-muted inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs">
      <span className="text-accent [&_svg]:size-3.5" aria-hidden>
        {icon}
      </span>
      {children}
    </span>
  )
}

/**
 * Facts about how the run was processed: the device, the configuration it is
 * scored under, the total stage time and how that compares with the
 * recording's length.
 */
function RunFacts({ run, stages }: { run: RunDetail; stages: StageInfo[] }) {
  const settings = (run.provenance.settings ?? {}) as Record<string, unknown>
  const total = stages.reduce((sum, stage) => sum + (stage.seconds ?? 0), 0)
  const transcript = stages.find((stage) => stage.name === 'transcript')
  const audioSeconds = Number(transcript?.counts?.audio_duration_sec)
  const gpu = settings.whisper_device === 'cuda'
  return (
    <div className="mb-4 flex flex-wrap gap-2">
      <Chip icon={gpu ? <Zap /> : <Cpu />}>
        {gpu ? 'GPU' : 'CPU'} · {String(settings.whisper_compute_type ?? '')}
      </Chip>
      <Chip icon={<Hash />}>
        config{' '}
        <code translate="no" className="text-fg font-mono">
          {String(run.provenance.config_hash ?? '').slice(0, 12)}
        </code>
      </Chip>
      {total > 0 ? <Chip icon={<Timer />}>{formatDuration(total)} of stage time</Chip> : null}
      {total > 0 && audioSeconds > 0 ? (
        <Chip icon={<Gauge />}>
          {total <= audioSeconds
            ? `${formatFixed(audioSeconds / total, 1)}× faster than real time`
            : `${formatFixed(total / audioSeconds, 1)}× the recording's length`}
        </Chip>
      ) : null}
    </div>
  )
}

export function PipelineFlow({
  run,
  stages,
  active,
}: {
  run: RunDetail
  stages: StageInfo[]
  active: boolean
}) {
  const reduceMotion = useReducedMotion()
  const rows = new Map(buildStageRows(stages, { mode: 'batch', active }).map((r) => [r.name, r]))
  const statusOf = (id: string): DisplayStatus =>
    id === 'audio' ? 'ok' : (rows.get(id)?.status ?? 'pending')
  const settings = (run.provenance.settings ?? {}) as Record<string, unknown>

  return (
    <figure>
      <RunFacts run={run} stages={stages} />
      <div className="relative w-full" style={{ aspectRatio: `${W} / ${H}` }}>
        <svg
          aria-hidden
          viewBox={`0 0 ${W} ${H}`}
          className="absolute inset-0 size-full overflow-visible"
        >
          {EDGES.map(([from, to]) => {
            const d = edgePath(BY_ID.get(from)!, BY_ID.get(to)!)
            const target = statusOf(to)
            const flowing = target === 'running'
            const done = target === 'ok'
            const failed = target === 'failed'
            return (
              <g key={`${from}-${to}`}>
                <path
                  d={d}
                  fill="none"
                  strokeWidth={done || flowing ? 2.2 : 1.5}
                  strokeLinecap="round"
                  strokeDasharray={done ? undefined : '6 6'}
                  className={cn(
                    flowing && 'animate-flow',
                    done ? 'stroke-accent' : failed ? 'stroke-danger' : 'stroke-border',
                  )}
                  style={{ opacity: done ? 0.85 : flowing ? 1 : 0.7 }}
                />
                {flowing && !reduceMotion ? (
                  <circle r={4} className="fill-accent">
                    <animateMotion dur="1.3s" repeatCount="indefinite" path={d} />
                  </circle>
                ) : null}
              </g>
            )
          })}
        </svg>
        <ol aria-label="Pipeline stages" className="absolute inset-0">
          {NODES.map((spec, index) => (
            <Node
              key={spec.id}
              spec={spec}
              status={statusOf(spec.id)}
              seconds={rows.get(spec.id)?.seconds}
              settings={settings}
              index={index}
            />
          ))}
        </ol>
      </div>
      <figcaption className="text-faint mt-3 text-xs">
        Whisper and pyannote both read the recording; alignment joins their output, and the
        language-model stages work from the language-tagged transcript.
      </figcaption>
    </figure>
  )
}
