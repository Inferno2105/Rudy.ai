import { DatabaseZap, ListMusic, Search, Upload } from 'lucide-react'
import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router'

import { useRebuildIndex, useRuns } from '../api/queries'
import type { RunSummary } from '../api/types'
import { PageHeader } from '../components/AppShell'
import { ErrorState } from '../components/states'
import { ModeLabel, OriginBadge, RunStatusBadge } from '../components/status'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { EmptyState, LoadingBlock } from '../components/ui/feedback'
import { Input, Select } from '../components/ui/field'
import { useToast } from '../components/ui/toast-context'
import { formatDateTime, runTitle, shortHash } from '../lib/format'
import { useDocumentTitle } from '../lib/utils'

function matches(run: RunSummary, query: string): boolean {
  if (!query) return true
  const needle = query.toLocaleLowerCase()
  return [run.run_id, runTitle(run)].some((value) => value.toLocaleLowerCase().includes(needle))
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

      <div className="mb-4 flex flex-wrap items-end gap-3">
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

      <Card>
        {runs.isPending ? (
          <div className="p-5">
            <LoadingBlock label="Loading meetings" lines={6} />
          </div>
        ) : runs.isError ? (
          <div className="p-5">
            <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
          </div>
        ) : visible.length === 0 ? (
          filtered ? (
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
              here after they finish (or use Rebuild index).
            </EmptyState>
          )
        ) : (
          <>
            <ul className="divide-border divide-y sm:hidden" aria-label="Meetings">
              {visible.map((run) => (
                <li key={run.run_id}>
                  <Link
                    to={`/runs/${encodeURIComponent(run.run_id)}`}
                    className="hover:bg-subtle/60 block px-4 py-3"
                  >
                    <span className="text-fg block truncate font-medium">{runTitle(run)}</span>
                    <span className="text-muted mt-0.5 block text-xs tabular-nums">
                      {formatDateTime(run.created_at)} · {run.mode === 'live' ? 'Live' : 'Batch'}
                    </span>
                    <span className="mt-2 flex flex-wrap gap-1.5">
                      <RunStatusBadge status={run.status} />
                      <OriginBadge origin={run.data_origin} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            <div className="hidden overflow-x-auto sm:block">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">
                  {visible.length} meeting{visible.length === 1 ? '' : 's'}
                </caption>
                <thead className="border-border text-muted border-b text-xs tracking-wide uppercase">
                  <tr>
                    <th scope="col" className="px-5 py-3 font-medium">
                      Meeting
                    </th>
                    <th scope="col" className="px-3 py-3 font-medium">
                      Date
                    </th>
                    <th scope="col" className="px-3 py-3 font-medium">
                      Mode
                    </th>
                    <th scope="col" className="px-3 py-3 font-medium">
                      Status
                    </th>
                    <th scope="col" className="px-3 py-3 font-medium">
                      Origin
                    </th>
                    <th scope="col" className="px-5 py-3 font-medium">
                      Config
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-border divide-y">
                  {visible.map((run) => (
                    <tr key={run.run_id} className="hover:bg-subtle/60 group">
                      <td className="max-w-xs px-5 py-3">
                        <Link
                          to={`/runs/${encodeURIComponent(run.run_id)}`}
                          className="text-fg group-hover:text-accent block truncate font-medium"
                        >
                          {runTitle(run)}
                        </Link>
                        <span
                          translate="no"
                          className="text-faint block truncate font-mono text-xs"
                        >
                          {run.run_id}
                        </span>
                      </td>
                      <td className="text-muted px-3 py-3 whitespace-nowrap tabular-nums">
                        {formatDateTime(run.created_at)}
                      </td>
                      <td className="px-3 py-3">
                        <ModeLabel mode={run.mode} />
                      </td>
                      <td className="px-3 py-3">
                        <RunStatusBadge status={run.status} />
                      </td>
                      <td className="px-3 py-3">
                        <OriginBadge origin={run.data_origin} />
                      </td>
                      <td
                        className="text-muted px-5 py-3 font-mono text-xs"
                        title={run.config_hash ?? undefined}
                      >
                        {shortHash(run.config_hash)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>
    </>
  )
}
