import { ArrowLeft, FileJson, FileText, Fingerprint, Mic, Sparkles, Users } from 'lucide-react'
import { lazy, Suspense } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { isNotFound } from '../../api/client'
import { useMetadata, useRun } from '../../api/queries'
import { isJobActive } from '../../api/types'
import { useRunEvents } from '../../api/useRunEvents'
import { PageHeader } from '../../components/AppShell'
import { StageProgress } from '../../components/StageProgress'
import { ErrorState } from '../../components/states'
import { JobStateBadge, ModeLabel, OriginBadge, RunStatusBadge } from '../../components/status'
import { Button } from '../../components/ui/button'
import { Card, CardBody, CardHeader } from '../../components/ui/card'
import { EmptyState, LoadingBlock } from '../../components/ui/feedback'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs'
import { formatCount, formatDateTime } from '../../lib/format'
import { STAGE_STATUS_TEXT, stageLabel } from '../../lib/stages'
import { runSourceName } from '../../lib/runs'
import { useDocumentTitle } from '../../lib/utils'
import { ArtifactsTab } from './ArtifactsTab'
import { ProvenanceTab } from './ProvenanceTab'
import { ResumeDialog } from './ResumeDialog'
import { SummaryTab } from './SummaryTab'
import { TranscriptTab } from './TranscriptTab'

// The speakers tab carries the charting library; load it only when opened.
const SpeakersTab = lazy(async () => ({ default: (await import('./SpeakersTab')).SpeakersTab }))

const TABS = ['transcript', 'summary', 'speakers', 'provenance', 'artifacts'] as const
type Tab = (typeof TABS)[number]

function MeetingFacts({ runId }: { runId: string }) {
  const metadata = useMetadata(runId)
  if (!metadata.data) return null
  const m = metadata.data
  return (
    <dl className="text-muted mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
      <div className="flex gap-1.5">
        <dt className="sr-only">Duration</dt>
        <dd className="tabular-nums">{m.duration_readable}</dd>
      </div>
      <div className="flex gap-1.5">
        <dt className="sr-only">Speakers</dt>
        <dd>
          {m.num_speakers} speaker{m.num_speakers === 1 ? '' : 's'}
        </dd>
      </div>
      <div className="flex gap-1.5">
        <dt className="sr-only">Languages</dt>
        <dd>{m.languages_used.join(', ') || 'No language tags'}</dd>
      </div>
      <div className="flex gap-1.5">
        <dt className="sr-only">Words</dt>
        <dd className="tabular-nums">{formatCount(m.total_word_count)} words</dd>
      </div>
    </dl>
  )
}

export function RunPage() {
  const { runId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const tab: Tab = TABS.includes(requested as Tab) ? (requested as Tab) : 'transcript'

  const run = useRun(runId)
  const active = isJobActive(run.data?.job)
  const events = useRunEvents(runId, active)
  useDocumentTitle(run.data ? runSourceName(run.data) : 'Meeting')

  if (run.isPending) return <LoadingBlock label="Loading meeting" lines={8} />
  if (run.isError) {
    return isNotFound(run.error) ? (
      <EmptyState
        icon={<FileText />}
        title="Meeting not found"
        action={
          <Button asChild>
            <Link to="/">Back to meetings</Link>
          </Button>
        }
      >
        No run with id{' '}
        <code translate="no" className="font-mono">
          {runId}
        </code>{' '}
        exists on this server.
      </EmptyState>
    ) : (
      <ErrorState error={run.error} onRetry={() => void run.refetch()} />
    )
  }

  const detail = run.data
  // Streamed state is fresher than the fetched run only while a job is active;
  // once it ends, the run is refetched and the fetched copy is authoritative.
  const streamed = active ? events : null
  const stages = streamed?.manifest?.stages ?? detail.stages
  const status = streamed?.manifest?.status ?? detail.status
  const job = streamed?.job ?? detail.job
  // Stages are appended as they finish, so the last one is the latest change.
  const latestStage = stages.at(-1)

  return (
    <>
      <Link to="/" className="text-muted hover:text-fg mb-3 inline-flex items-center gap-1 text-sm">
        <ArrowLeft className="size-4" aria-hidden /> Meetings
      </Link>
      <PageHeader
        title={runSourceName(detail)}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {/* Mid-run the manifest still says "partial"; the job state is the truth. */}
            {job && active ? (
              <JobStateBadge state={job.state} />
            ) : (
              <RunStatusBadge status={status} />
            )}
            <OriginBadge origin={detail.data_origin} />
            <ModeLabel mode={detail.mode} />
            <span aria-hidden>·</span>
            <span>{formatDateTime(detail.provenance.captured_at as string | undefined)}</span>
            <span translate="no" className="text-faint font-mono text-xs">
              {detail.run_id}
            </span>
          </span>
        }
        actions={
          detail.mode === 'batch' && !active ? <ResumeDialog run={{ ...detail, stages }} /> : null
        }
      >
        <MeetingFacts runId={runId} />
      </PageHeader>

      {active ? (
        <Card className="mb-6">
          <CardHeader
            title={detail.mode === 'live' ? 'Recording in progress' : 'Processing'}
            description={
              events.status === 'reconnecting'
                ? 'Connection lost, reconnecting…'
                : 'Updates arrive as each stage finishes.'
            }
            actions={
              detail.mode === 'live' ? (
                <Button asChild size="sm" variant="primary">
                  <Link to="/live">
                    <Mic aria-hidden /> Open live view
                  </Link>
                </Button>
              ) : null
            }
          />
          <CardBody>
            <StageProgress stages={stages} mode={detail.mode} active={active} />
            {/* Announces only the newest change, not the whole list on every update. */}
            <output className="sr-only">
              {latestStage
                ? `${stageLabel(latestStage.name)} ${STAGE_STATUS_TEXT[latestStage.status] ?? latestStage.status}`
                : ''}
            </output>
          </CardBody>
        </Card>
      ) : null}

      <Tabs
        value={tab}
        onValueChange={(value) => {
          const next = new URLSearchParams(params)
          if (value === 'transcript') next.delete('tab')
          else next.set('tab', value)
          setParams(next, { replace: true })
        }}
      >
        <TabsList aria-label="Meeting views">
          <TabsTrigger value="transcript">
            <FileText aria-hidden /> Transcript
          </TabsTrigger>
          <TabsTrigger value="summary">
            <Sparkles aria-hidden /> Summary
          </TabsTrigger>
          <TabsTrigger value="speakers">
            <Users aria-hidden /> Speakers
          </TabsTrigger>
          <TabsTrigger value="provenance">
            <Fingerprint aria-hidden /> Provenance
          </TabsTrigger>
          <TabsTrigger value="artifacts">
            <FileJson aria-hidden /> Artifacts
          </TabsTrigger>
        </TabsList>
        <TabsContent value="transcript">
          <TranscriptTab
            run={detail}
            stages={stages}
            liveSegments={active ? events.segments : null}
          />
        </TabsContent>
        <TabsContent value="summary">
          <SummaryTab run={detail} stages={stages} />
        </TabsContent>
        <TabsContent value="speakers">
          <Suspense fallback={<LoadingBlock label="Loading speaker statistics" lines={6} />}>
            <SpeakersTab run={detail} stages={stages} />
          </Suspense>
        </TabsContent>
        <TabsContent value="provenance">
          <ProvenanceTab run={detail} />
        </TabsContent>
        <TabsContent value="artifacts">
          <ArtifactsTab run={detail} />
        </TabsContent>
      </Tabs>
    </>
  )
}
