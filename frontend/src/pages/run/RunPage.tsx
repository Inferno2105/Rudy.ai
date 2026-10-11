import {
  ArrowLeft,
  Clock,
  FileJson,
  FileText,
  Fingerprint,
  Languages,
  Mic,
  Sparkles,
  Trash2,
  Type,
  Users,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { lazy, Suspense } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'

import { isNotFound } from '../../api/client'
import { useDeleteRun, useMetadata, useRun } from '../../api/queries'
import { isJobActive } from '../../api/types'
import { useRunEvents } from '../../api/useRunEvents'
import { PageHeader } from '../../components/AppShell'
import { ConfirmDelete } from '../../components/ConfirmDelete'
import { PipelineFlow } from '../../components/PipelineFlow'
import { StageProgress } from '../../components/StageProgress'
import { ErrorState } from '../../components/states'
import { JobStateBadge, ModeLabel, OriginBadge, RunStatusBadge } from '../../components/status'
import { Button } from '../../components/ui/button'
import { Card, CardBody, CardHeader } from '../../components/ui/card'
import { useToast } from '../../components/ui/toast-context'
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

function Fact({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="glass flex items-center gap-2 rounded-full py-1.5 pr-3.5 pl-2 text-sm">
      <span className="text-accent [&_svg]:size-4" aria-hidden>
        {icon}
      </span>
      <dt className="sr-only">{label}</dt>
      <dd className="text-fg tabular-nums">{children}</dd>
    </div>
  )
}

function MeetingFacts({ runId }: { runId: string }) {
  const metadata = useMetadata(runId)
  if (!metadata.data) return null
  const m = metadata.data
  return (
    <dl className="mt-5 flex flex-wrap gap-2">
      <Fact icon={<Clock />} label="Duration">
        {m.duration_readable}
      </Fact>
      <Fact icon={<Users />} label="Speakers">
        {m.num_speakers} speaker{m.num_speakers === 1 ? '' : 's'}
      </Fact>
      <Fact icon={<Languages />} label="Languages">
        {m.languages_used.join(', ') || 'No language tags'}
      </Fact>
      <Fact icon={<Type />} label="Words">
        {formatCount(m.total_word_count)} words
      </Fact>
    </dl>
  )
}

export function RunPage() {
  const { runId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const tab: Tab = TABS.includes(requested as Tab) ? (requested as Tab) : 'transcript'

  const run = useRun(runId)
  const deleteRun = useDeleteRun()
  const navigate = useNavigate()
  const notify = useToast()
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
            <Link to="/meetings">Back to meetings</Link>
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
      <Link
        to="/meetings"
        className="text-muted hover:text-fg group mb-4 inline-flex items-center gap-1 text-sm"
      >
        <ArrowLeft
          className="size-4 transition-transform group-hover:-translate-x-0.5"
          aria-hidden
        />{' '}
        Meetings
      </Link>
      <PageHeader
        eyebrow={detail.mode === 'live' ? 'Live session' : 'Meeting'}
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
          active ? null : (
            <div className="flex flex-wrap gap-2">
              {detail.mode === 'batch' ? <ResumeDialog run={{ ...detail, stages }} /> : null}
              <ConfirmDelete
                title="Delete this meeting?"
                confirmLabel="Delete meeting"
                trigger={
                  <Button variant="ghost">
                    <Trash2 aria-hidden /> Delete
                  </Button>
                }
                onConfirm={async () => {
                  await deleteRun.mutateAsync(detail.run_id)
                  notify({ tone: 'success', title: `Deleted ${runSourceName(detail)}` })
                  navigate('/meetings', { replace: true })
                }}
              >
                <p>
                  Its transcript, summary, action items, statistics and provenance are removed for
                  good. This cannot be undone.
                </p>
                <p>
                  The recording it was made from is kept; delete it from{' '}
                  <span className="text-fg">New run</span> if you no longer need it.
                </p>
              </ConfirmDelete>
            </div>
          )
        }
      >
        <MeetingFacts runId={runId} />
      </PageHeader>

      {active ? (
        <Card className="mb-8">
          <CardHeader
            icon={<Sparkles />}
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
            {detail.mode === 'batch' ? (
              <>
                <div className="hidden lg:block">
                  <PipelineFlow run={detail} stages={stages} active={active} />
                </div>
                <div className="lg:hidden">
                  <StageProgress stages={stages} mode={detail.mode} active={active} />
                </div>
              </>
            ) : (
              <StageProgress stages={stages} mode={detail.mode} active={active} />
            )}
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
            key={params.get('t') ?? ''}
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
