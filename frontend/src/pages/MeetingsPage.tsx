import {
  CheckCircle2,
  Clock,
  DatabaseZap,
  Languages,
  ListMusic,
  Mic,
  Search,
  Upload,
  Waves,
} from 'lucide-react'
import { useMemo, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router'

import { useRebuildIndex, useRuns } from '../api/queries'
import type { RunSummary } from '../api/types'
import { PageHeader } from '../components/AppShell'
import { CountUp, StaggerItem, StaggerList } from '../components/motion'
import { ErrorState } from '../components/states'
import { OriginBadge, RunStatusBadge } from '../components/status'
import { Button } from '../components/ui/button'
import { Card, IconChip } from '../components/ui/card'
import { EmptyState, Skeleton } from '../components/ui/feedback'
import { Input, Select } from '../components/ui/field'
import { useToast } from '../components/ui/toast-context'
import { AvatarStack, LanguageMixBar } from '../components/visuals'
import { formatDateTime, formatDuration, runTitle, shortHash } from '../lib/format'
import { speakerPalette } from '../lib/speakers'
import { useDocumentTitle } from '../lib/utils'

function matches(run: RunSummary, query: string): boolean {
  if (!query) return true
  const needle = query.toLocaleLowerCase()
  return [run.run_id, runTitle(run)].some((value) => value.toLocaleLowerCase().includes(needle))
}

function StatTile({
  icon,
  label,
  children,
}: {
  icon: ReactNode
  label: string
  children: ReactNode
}) {
  return (
    <StaggerItem as="div">
      <Card className="relative overflow-hidden px-5 py-4">
        <div
          aria-hidden
          className="bg-brand pointer-events-none absolute -top-10 -right-10 size-28 rounded-full opacity-15 blur-2xl"
        />
        <div className="flex items-center gap-3">
          <IconChip>{icon}</IconChip>
          <p className="text-muted text-xs font-medium tracking-wide uppercase">{label}</p>
        </div>
        <p className="font-display text-fg mt-3 text-3xl font-semibold tabular-nums">{children}</p>
      </Card>
    </StaggerItem>
  )
}

function Stats({ runs }: { runs: RunSummary[] }) {
  const minutes = runs.reduce((sum, run) => sum + (run.duration_sec ?? 0), 0) / 60
  const languages = new Set(runs.flatMap((run) => Object.keys(run.language_mix ?? {}))).size
  const completed = runs.filter((run) => run.status === 'completed').length
  return (
    <StaggerList as="div" className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
      <StatTile icon={<ListMusic />} label="Meetings">
        <CountUp value={runs.length} />
      </StatTile>
      <StatTile icon={<Clock />} label="Minutes of speech">
        <CountUp value={minutes} digits={1} />
      </StatTile>
      <StatTile icon={<Languages />} label="Languages heard">
        <CountUp value={languages} />
      </StatTile>
      <StatTile icon={<CheckCircle2 />} label="Completed">
        <CountUp value={completed} />
      </StatTile>
    </StaggerList>
  )
}

function MeetingCard({ run }: { run: RunSummary }) {
  const speakers = run.speakers ?? []
  const palette = speakerPalette(speakers)
  return (
    // The title is the link; its ::after stretches over the card so the whole
    // card is clickable while the link's accessible name stays the title.
    <Card interactive className="group relative h-full">
      <div className="flex h-full flex-col gap-4 p-5">
        <div className="flex items-start justify-between gap-3">
          <span className="bg-subtle text-muted grid size-10 shrink-0 place-items-center rounded-xl [&_svg]:size-5">
            {run.mode === 'live' ? <Mic aria-hidden /> : <Waves aria-hidden />}
          </span>
          <span className="flex flex-wrap justify-end gap-1.5">
            <RunStatusBadge status={run.status} />
            {run.data_origin !== 'real_audio' ? <OriginBadge origin={run.data_origin} /> : null}
          </span>
        </div>
        <div className="min-w-0">
          <h2 className="font-display text-fg group-hover:text-accent truncate text-lg font-semibold transition-colors">
            <Link
              to={`/runs/${encodeURIComponent(run.run_id)}`}
              className="focus-visible:after:outline-ring rounded-sm after:absolute after:inset-0 after:rounded-2xl focus-visible:outline-none focus-visible:after:outline-2"
            >
              {runTitle(run)}
            </Link>
          </h2>
          <p className="text-muted mt-0.5 text-sm tabular-nums">
            {formatDateTime(run.created_at)}
            {run.duration_sec != null ? ` · ${formatDuration(run.duration_sec)}` : ''}
            {` · ${run.mode === 'live' ? 'Live' : 'Batch'}`}
          </p>
        </div>
        <LanguageMixBar mix={run.language_mix ?? {}} />
        <div className="mt-auto flex items-center justify-between gap-3">
          <AvatarStack speakers={speakers} palette={palette} />
          <span translate="no" className="text-faint font-mono text-[11px]">
            {shortHash(run.config_hash)}
          </span>
        </div>
      </div>
    </Card>
  )
}

export function MeetingsPage() {
  useDocumentTitle('Meetings')
  // Filters live in the URL so a filtered view can be linked and survives reload.
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? ''
  const mode = params.get('mode') ?? ''
  const query = params.get('q') ?? ''

  const runs = useRuns({ status: status || undefined, mode: mode || undefined })
  const rebuild = useRebuildIndex()
  const notify = useToast()

  const visible = useMemo(
    () => (runs.data ?? []).filter((run) => matches(run, query)),
    [runs.data, query],
  )

  function setParam(name: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(name, value)
    else next.delete(name)
    setParams(next, { replace: true })
  }

  function rebuildIndex() {
    rebuild.mutate(undefined, {
      onSuccess: (result) =>
        notify({
          tone: 'success',
          title: 'Index rebuilt',
          description: `Indexed ${result.indexed} of ${result.total} runs from disk.`,
        }),
      onError: (error) =>
        notify({
          tone: 'danger',
          title: 'Could not rebuild the index',
          description: error.message,
        }),
    })
  }

  const filtered = Boolean(status || mode || query)

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Meetings"
        description="Every processed recording and live session, newest first."
        actions={
          <>
            <Button
              variant="ghost"
              onClick={rebuildIndex}
              disabled={rebuild.isPending}
              title="Re-read every run directory on disk into the index"
            >
              <DatabaseZap aria-hidden /> {rebuild.isPending ? 'Rebuilding…' : 'Rebuild index'}
            </Button>
            <Button asChild variant="primary">
              <Link to="/new">
                <Upload aria-hidden /> New run
              </Link>
            </Button>
          </>
        }
      />

      {runs.data && runs.data.length > 0 && !filtered ? <Stats runs={runs.data} /> : null}

      <div className="glass mb-6 flex flex-wrap items-end gap-3 rounded-2xl p-3">
        <div className="relative min-w-56 flex-1">
          <label htmlFor="meeting-search" className="sr-only">
            Search meetings
          </label>
          <Search
            className="text-faint pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
            aria-hidden
          />
          <Input
            id="meeting-search"
            name="q"
            type="search"
            placeholder="Search by recording or run id…"
            value={query}
            onChange={(event) => setParam('q', event.target.value)}
            className="pl-9"
            autoComplete="off"
          />
        </div>
        <div className="w-40">
          <label htmlFor="status-filter" className="sr-only">
            Status
          </label>
          <Select
            id="status-filter"
            value={status}
            onChange={(event) => setParam('status', event.target.value)}
          >
            <option value="">All statuses</option>
            <option value="completed">Completed</option>
            <option value="partial">Partial</option>
            <option value="failed">Failed</option>
          </Select>
        </div>
        <div className="w-36">
          <label htmlFor="mode-filter" className="sr-only">
            Mode
          </label>
          <Select
            id="mode-filter"
            value={mode}
            onChange={(event) => setParam('mode', event.target.value)}
          >
            <option value="">All modes</option>
            <option value="batch">Batch</option>
            <option value="live">Live</option>
          </Select>
        </div>
      </div>

      {runs.isPending ? (
        <output className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <span className="sr-only">Loading meetings…</span>
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-52 rounded-2xl" />
          ))}
        </output>
      ) : runs.isError ? (
        <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
      ) : visible.length === 0 ? (
        <Card>
          {filtered ? (
            <EmptyState icon={<Search />} title="No meetings match these filters">
              <button
                type="button"
                className="text-accent underline-offset-2 hover:underline"
                onClick={() => setParams(new URLSearchParams(), { replace: true })}
              >
                Clear filters
              </button>
            </EmptyState>
          ) : (
            <EmptyState
              icon={<ListMusic />}
              title="No meetings yet"
              action={
                <Button asChild variant="primary">
                  <Link to="/new">Process a recording</Link>
                </Button>
              }
            >
              Upload a recording or start a live session. Runs made from the command line appear
              here after they finish, or after Rebuild index above.
            </EmptyState>
          )}
        </Card>
      ) : (
        <StaggerList
          aria-label={`${visible.length} meeting${visible.length === 1 ? '' : 's'}`}
          className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
        >
          {visible.map((run) => (
            <StaggerItem key={run.run_id}>
              <MeetingCard run={run} />
            </StaggerItem>
          ))}
        </StaggerList>
      )}
    </>
  )
}
