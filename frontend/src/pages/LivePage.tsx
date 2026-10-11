import { ArrowDown, CircleStop, ExternalLink, Mic } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react'
import { Link } from 'react-router'

import { useCurrentJob, useDevices, useStartLive, useStopLive } from '../api/queries'
import { isJobActive } from '../api/types'
import { useRunEvents } from '../api/useRunEvents'
import { PageHeader } from '../components/AppShell'
import { ErrorState } from '../components/states'
import { JobStateBadge } from '../components/status'
import { Transcript } from '../components/Transcript'
import { Button } from '../components/ui/button'
import { Card, CardBody, CardHeader } from '../components/ui/card'
import { Callout, EmptyState, LoadingBlock } from '../components/ui/feedback'
import { Field, Input, Select, Switch } from '../components/ui/field'
import { formatClock, formatFixed, NBSP, plural } from '../lib/format'
import { speakerPalette } from '../lib/speakers'
import { useDocumentTitle } from '../lib/utils'

function useElapsed(startedAt: string | null | undefined, running: boolean): number | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])
  if (!startedAt) return null
  const started = new Date(startedAt).getTime()
  return Number.isNaN(started) ? null : Math.max(0, (now - started) / 1000)
}

function StartForm({ onStarted }: { onStarted: (runId: string) => void }) {
  const devices = useDevices()
  const start = useStartLive()
  const [device, setDevice] = useState<string>('')
  const [speakers, setSpeakers] = useState('')
  const [useRegistry, setUseRegistry] = useState(true)
  const speakersInput = useRef<HTMLInputElement>(null)

  const defaultDevice = devices.data?.find((d) => d.is_default)?.index
  const selectedDevice = device === '' ? (defaultDevice ?? null) : Number(device)
  const speakerCount = speakers.trim() === '' ? null : Number(speakers)
  const speakersInvalid =
    speakerCount !== null &&
    (!Number.isInteger(speakerCount) || speakerCount < 1 || speakerCount > 20)

  function submit(event: FormEvent) {
    event.preventDefault()
    if (speakersInvalid) {
      speakersInput.current?.focus()
      return
    }
    start.mutate(
      { device: selectedDevice, num_speakers: speakerCount, use_registry: useRegistry },
      { onSuccess: (accepted) => onStarted(accepted.run_id) },
    )
  }

  return (
    <Card className="max-w-xl">
      <CardHeader
        title="Start a live session"
        description="Records from the server's microphone and transcribes as you speak."
      />
      <CardBody>
        <form onSubmit={submit} className="space-y-5">
          <Field label="Microphone">
            {({ id }) =>
              devices.isPending ? (
                <LoadingBlock label="Loading microphones" lines={1} />
              ) : devices.isError ? (
                <ErrorState error={devices.error} onRetry={() => void devices.refetch()} />
              ) : devices.data.length === 0 ? (
                <p className="text-danger text-sm">
                  The server has no input device. Connect a microphone to the server machine, then
                  reload this page.
                </p>
              ) : (
                <Select
                  id={id}
                  value={device === '' ? String(defaultDevice ?? '') : device}
                  onChange={(event) => setDevice(event.target.value)}
                >
                  {devices.data.map((d) => (
                    <option key={d.index} value={d.index}>
                      {d.name}
                      {d.is_default ? ' (default)' : ''}
                    </option>
                  ))}
                </Select>
              )
            }
          </Field>
          <Field
            label="Number of speakers"
            hint="Optional upper bound for each chunk's diarization. Leave blank to detect automatically."
            error={speakersInvalid ? 'Enter a whole number from 1 to 20.' : undefined}
          >
            {({ id, describedBy }) => (
              <Input
                ref={speakersInput}
                id={id}
                aria-describedby={describedBy}
                aria-invalid={speakersInvalid || undefined}
                name="num_speakers"
                autoComplete="off"
                inputMode="numeric"
                placeholder="e.g. 3…"
                value={speakers}
                onChange={(event) => setSpeakers(event.target.value)}
              />
            )}
          </Field>
          <Switch
            checked={useRegistry}
            onCheckedChange={setUseRegistry}
            label="Track speakers across chunks"
            description="Matches voices between chunks so a speaker keeps one label for the whole session."
          />
          {start.isError ? (
            <Callout tone="danger" title="Could not start recording" announce="alert">
              {start.error.message}
            </Callout>
          ) : null}
          <Button type="submit" variant="primary" disabled={start.isPending}>
            <Mic aria-hidden /> {start.isPending ? 'Starting…' : 'Start recording'}
          </Button>
        </form>
      </CardBody>
    </Card>
  )
}

interface LiveStats {
  chunks_recorded?: number
  chunks_processed?: number
  max_backlog?: number
  mean_chunk_latency_sec?: number
  realtime_factor?: number
}

function Session({ runId, onReset }: { runId: string; onReset: () => void }) {
  const events = useRunEvents(runId, true)
  const stop = useStopLive()
  const job = events.job
  const running = job?.state === 'running'
  const stopping = job?.state === 'stopping' || stop.isPending
  const elapsed = useElapsed(job?.started_at, running)
  const stats = (events.manifest?.extra?.live_stats ?? null) as LiveStats | null

  const palette = useMemo(
    () => speakerPalette(events.segments.map((s) => s.speaker)),
    [events.segments],
  )

  // Follow new segments unless the reader has scrolled up to re-read.
  // A ref to scroll it, and state to hand the element to the transcript's
  // virtualizer once it exists.
  const listRef = useRef<HTMLElement | null>(null)
  const [list, setList] = useState<HTMLElement | null>(null)
  const attachList = useCallback((node: HTMLElement | null) => {
    listRef.current = node
    setList(node)
  }, [])
  const [pinned, setPinned] = useState(true)
  const segmentCount = events.segments.length
  useLayoutEffect(() => {
    const element = listRef.current
    if (pinned && segmentCount > 0 && element) element.scrollTop = element.scrollHeight
  }, [segmentCount, pinned])

  const finished = events.ended
  const failed = job?.state === 'failed'

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
      <Card className="flex min-h-[28rem] flex-col">
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              {running ? (
                <span className="relative flex size-2.5" aria-hidden>
                  <span className="bg-danger absolute inline-flex size-full animate-ping rounded-full opacity-60 motion-reduce:animate-none" />
                  <span className="bg-danger relative inline-flex size-2.5 rounded-full" />
                </span>
              ) : null}
              {finished ? 'Session finished' : stopping ? 'Finishing…' : 'Recording'}
            </span>
          }
          description={
            stopping && !finished
              ? 'Processing audio that was still queued. This can take a moment.'
              : undefined
          }
          actions={
            finished ? (
              <>
                <Button asChild variant="primary" size="sm">
                  <Link to={`/runs/${encodeURIComponent(runId)}`}>
                    <ExternalLink aria-hidden /> Open meeting
                  </Link>
                </Button>
                <Button size="sm" onClick={onReset}>
                  New session
                </Button>
              </>
            ) : (
              <Button
                variant="danger"
                size="sm"
                onClick={() => stop.mutate()}
                disabled={!running || stop.isPending}
              >
                <CircleStop aria-hidden /> Stop
              </Button>
            )
          }
        />
        <div className="relative flex-1">
          {/* Focusable so keyboard users can scroll it; named so the focus stop makes sense. */}
          <section
            ref={attachList}
            aria-label="Live transcript, scrollable"
            tabIndex={0}
            onScroll={(event) => {
              const el = event.currentTarget
              setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 48)
            }}
            className="absolute inset-0 overflow-y-auto overscroll-contain px-5 py-4"
          >
            {events.segments.length === 0 ? (
              <EmptyState
                icon={<Mic />}
                title={finished ? 'Nothing was transcribed' : 'Listening…'}
              >
                {finished
                  ? 'No speech was detected during the session.'
                  : 'Segments appear here a few seconds after each pause in speech.'}
              </EmptyState>
            ) : (
              <Transcript
                segments={events.segments}
                palette={palette}
                label="Live transcript"
                scrollElement={list}
              />
            )}
          </section>
          {!pinned ? (
            <Button
              size="sm"
              variant="primary"
              className="absolute bottom-3 left-1/2 -translate-x-1/2 shadow-lg"
              onClick={() => setPinned(true)}
            >
              <ArrowDown aria-hidden /> Jump to latest
            </Button>
          ) : null}
        </div>
        <p className="sr-only" aria-live="polite">
          {plural(events.segments.length, 'segment')} transcribed
        </p>
      </Card>

      <div className="space-y-4">
        <Card>
          <CardBody className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-muted text-sm">Status</span>
              {job ? (
                <JobStateBadge state={job.state} />
              ) : (
                <span className="text-muted text-sm">Connecting…</span>
              )}
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted text-sm">Elapsed</span>
              <span translate="no" className="text-fg font-mono text-sm tabular-nums">
                {elapsed != null ? formatClock(elapsed) : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted text-sm">Segments</span>
              <span className="text-fg text-sm tabular-nums">{events.segments.length}</span>
            </div>
            {events.status === 'reconnecting' ? (
              <Callout tone="warning">Connection lost, reconnecting…</Callout>
            ) : null}
          </CardBody>
        </Card>
        {stats ? (
          <Card>
            <CardHeader title="Session statistics" headingLevel={3} />
            <CardBody>
              <dl className="space-y-2 text-sm">
                {(
                  [
                    ['Chunks recorded', stats.chunks_recorded],
                    ['Chunks processed', stats.chunks_processed],
                    ['Max backlog', stats.max_backlog],
                    [
                      'Mean chunk latency',
                      stats.mean_chunk_latency_sec != null
                        ? `${formatFixed(stats.mean_chunk_latency_sec, 2)}${NBSP}s`
                        : undefined,
                    ],
                    [
                      'Real-time factor',
                      stats.realtime_factor != null
                        ? formatFixed(stats.realtime_factor, 3)
                        : undefined,
                    ],
                  ] as const
                )
                  .filter(([, value]) => value !== undefined)
                  .map(([label, value]) => (
                    <div key={label} className="flex justify-between gap-3">
                      <dt className="text-muted">{label}</dt>
                      <dd className="text-fg tabular-nums">{value}</dd>
                    </div>
                  ))}
              </dl>
              {stats.chunks_recorded != null &&
              stats.chunks_processed != null &&
              stats.chunks_recorded !== stats.chunks_processed ? (
                <Callout tone="warning" className="mt-3">
                  Not every recorded chunk was processed.
                </Callout>
              ) : null}
            </CardBody>
          </Card>
        ) : null}
        {failed ? (
          <ErrorState
            title="The session failed"
            error={
              new Error(
                job?.error ??
                  `It stopped without reporting why. Check data/runs/${runId}/run.log on the server, then start a new session.`,
              )
            }
          />
        ) : null}
      </div>
    </div>
  )
}

export function LivePage() {
  useDocumentTitle('Live')
  const current = useCurrentJob()
  const [startedRunId, setStartedRunId] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState<string | null>(null)

  // Attach to a live session already running (e.g. after a reload).
  const attached =
    current.data && current.data.kind === 'live' && isJobActive(current.data)
      ? current.data.run_id
      : null
  const runId = startedRunId ?? (attached !== dismissed ? attached : null)
  const busyOther =
    !runId && current.data && isJobActive(current.data) && current.data.kind !== 'live'
      ? current.data
      : null

  return (
    <>
      <PageHeader
        title="Live"
        description="Transcribe a meeting as it happens, from the microphone attached to the server."
      />
      {runId ? (
        <Session
          key={runId}
          runId={runId}
          onReset={() => {
            setDismissed(runId)
            setStartedRunId(null)
          }}
        />
      ) : (
        <div className="space-y-4">
          {busyOther ? (
            <Callout tone="warning" title="The server is busy">
              A {busyOther.kind} job is running. Live recording can start once it finishes.{' '}
              <Link
                className="text-accent underline"
                to={`/runs/${encodeURIComponent(busyOther.run_id)}`}
              >
                View it
              </Link>
            </Callout>
          ) : null}
          <StartForm onStarted={setStartedRunId} />
        </div>
      )}
    </>
  )
}
