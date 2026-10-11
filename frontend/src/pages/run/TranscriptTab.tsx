import { LocateFixed, Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'

import { isNotFound } from '../../api/client'
import { useArtifact, useTranscript } from '../../api/queries'
import type { RunDetail, Segment, StageInfo } from '../../api/types'
import { MeetingPlayer, type MeetingPlayerHandle } from '../../components/MeetingPlayer'
import { SpeakerTimeline } from '../../components/SpeakerTimeline'
import { ErrorState, NotProduced } from '../../components/states'
import { LanguageLegend } from '../../components/status'
import { Transcript } from '../../components/Transcript'
import { Card, CardBody } from '../../components/ui/card'
import { Callout, LoadingBlock } from '../../components/ui/feedback'
import { Input } from '../../components/ui/field'
import { matchesQuery } from '../../lib/runs'
import { speakerPalette } from '../../lib/speakers'
import { cn } from '../../lib/utils'

type Script = 'romanized' | 'original'

function asSegments(value: unknown): Segment[] | null {
  return Array.isArray(value) ? (value as Segment[]) : null
}

const SOURCE_LABEL: Record<string, string> = {
  hinglish: 'the transcript normalized to Romanized Hinglish',
  tagged: 'the transcript in its original script, with language tags',
  merged: 'speaker turns before language tagging',
  aligned: 'speaker-aligned segments before turns were merged',
}

function ScriptToggle({ value, onChange }: { value: Script; onChange: (s: Script) => void }) {
  const options = [
    ['romanized', 'Romanized'],
    ['original', 'Original script'],
  ] as const
  return (
    <fieldset className="bg-subtle inline-flex rounded-md p-0.5">
      <legend className="sr-only">Script</legend>
      {options.map(([option, label]) => (
        <label
          key={option}
          className={cn(
            'has-[:focus-visible]:outline-ring cursor-pointer rounded px-2.5 py-1 text-xs font-medium transition-colors has-[:focus-visible]:outline-2',
            value === option ? 'bg-surface text-fg shadow-xs' : 'text-muted hover:text-fg',
          )}
        >
          <input
            type="radio"
            name="transcript-script"
            value={option}
            checked={value === option}
            onChange={() => onChange(option)}
            className="sr-only"
          />
          {label}
        </label>
      ))}
    </fieldset>
  )
}

export function TranscriptTab({
  run,
  stages,
  liveSegments,
}: {
  run: RunDetail
  stages: StageInfo[]
  liveSegments: Segment[] | null
}) {
  const transcript = useTranscript(run.run_id)
  const canToggle = run.artifacts.includes('hinglish') && run.artifacts.includes('tagged')
  const [script, setScript] = useState<Script>('romanized')
  const original = useArtifact(run.run_id, 'tagged', canToggle && script === 'original')
  const [query, setQuery] = useState('')
  // A link to a moment (?t=seconds, from search) starts with that line
  // current; the run page remounts this tab when ?t changes.
  const [params] = useSearchParams()
  const jumpTo = Number.parseFloat(params.get('t') ?? '')
  const [currentTime, setCurrentTime] = useState<number | null>(
    Number.isFinite(jumpTo) ? jumpTo : null,
  )
  const player = useRef<MeetingPlayerHandle>(null)
  // Follow the playing line until the reader scrolls away themselves.
  const [follow, setFollow] = useState(true)
  const [morphKey, setMorphKey] = useState(0)

  const segments: Segment[] | null =
    liveSegments && liveSegments.length > 0
      ? liveSegments
      : script === 'original' && canToggle
        ? asSegments(original.data)
        : (transcript.data?.segments ?? null)

  const palette = useMemo(() => speakerPalette((segments ?? []).map((s) => s.speaker)), [segments])
  const visible = useMemo(
    () => (segments ?? []).filter((segment) => matchesQuery(segment, query)),
    [segments, query],
  )

  const hasRecording = run.mode === 'batch' && run.provenance.input != null

  useEffect(() => {
    const stopFollowing = () => setFollow(false)
    window.addEventListener('wheel', stopFollowing, { passive: true })
    window.addEventListener('touchmove', stopFollowing, { passive: true })
    return () => {
      window.removeEventListener('wheel', stopFollowing)
      window.removeEventListener('touchmove', stopFollowing)
    }
  }, [])

  // Cue the recording at the linked moment once the player exists, without
  // starting playback.
  const segmentsReady = Boolean(segments?.length)
  useEffect(() => {
    if (segmentsReady && Number.isFinite(jumpTo)) player.current?.seek(jumpTo, { play: false })
  }, [segmentsReady, jumpTo])

  function seek(seconds: number) {
    setFollow(true)
    player.current?.seek(seconds)
  }

  // The sticky player sits under the sticky header; widen the page's scroll
  // padding to clear both, so a segment reached with Tab is never hidden.
  useEffect(() => {
    if (!hasRecording) return
    const root = document.documentElement
    const previous = root.style.scrollPaddingTop
    root.style.scrollPaddingTop = '15rem'
    return () => {
      root.style.scrollPaddingTop = previous
    }
  }, [hasRecording])

  if (!segments) {
    if (transcript.isPending || (script === 'original' && original.isPending)) {
      return <LoadingBlock label="Loading transcript" lines={8} />
    }
    if (transcript.isError && !isNotFound(transcript.error)) {
      return <ErrorState error={transcript.error} onRetry={() => void transcript.refetch()} />
    }
    return (
      <Card>
        <NotProduced stage="aligned" stages={stages} what="transcript" />
      </Card>
    )
  }

  const source = liveSegments?.length
    ? 'live'
    : script === 'original'
      ? 'tagged'
      : transcript.data?.source_artifact

  return (
    <div className="space-y-4">
      {hasRecording ? (
        // Player and timeline stay in view while the transcript scrolls.
        <div className="glass sticky top-16 z-20 space-y-3 rounded-2xl p-3">
          <MeetingPlayer
            ref={player}
            runId={run.run_id}
            segments={segments}
            palette={palette}
            onTimeUpdate={setCurrentTime}
          />
        </div>
      ) : (
        <Card className="p-4">
          <SpeakerTimeline segments={segments} palette={palette} />
        </Card>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative max-w-sm min-w-56 flex-1">
          <label htmlFor="transcript-search" className="sr-only">
            Search the transcript
          </label>
          <Search
            className="text-faint pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
            aria-hidden
          />
          <Input
            id="transcript-search"
            type="search"
            placeholder="Search the transcript…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="pl-9"
            autoComplete="off"
          />
        </div>
        <div className="flex items-center gap-3">
          <span className="text-muted text-xs" aria-live="polite">
            {query
              ? `${visible.length} of ${segments.length} segments match`
              : `${segments.length} segment${segments.length === 1 ? '' : 's'}`}
          </span>
          {canToggle && !liveSegments?.length ? (
            <ScriptToggle
              value={script}
              onChange={(next) => {
                setScript(next)
                setMorphKey((key) => key + 1)
              }}
            />
          ) : null}
        </div>
      </div>

      {source && SOURCE_LABEL[source] ? (
        <p className="text-muted text-xs">Showing {SOURCE_LABEL[source]}.</p>
      ) : null}
      <LanguageLegend languages={segments.map((segment) => segment.language)} />
      {source === 'live' ? (
        <Callout tone="info">Live transcript: segments appear as each chunk is processed.</Callout>
      ) : null}

      <Card>
        <CardBody>
          {visible.length === 0 ? (
            <p className="text-muted py-6 text-center text-sm">No segment contains “{query}”.</p>
          ) : (
            <Transcript
              segments={visible}
              palette={palette}
              query={query}
              currentTime={currentTime}
              onSeek={hasRecording ? seek : undefined}
              follow={follow && !query}
              morphKey={morphKey}
            />
          )}
        </CardBody>
      </Card>

      {!follow && currentTime != null && !query ? (
        <button
          type="button"
          onClick={() => setFollow(true)}
          className="glass text-fg animate-enter fixed right-6 bottom-6 z-30 inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium shadow-lg"
        >
          <LocateFixed className="text-accent size-4" aria-hidden /> Follow along
        </button>
      ) : null}
    </div>
  )
}
