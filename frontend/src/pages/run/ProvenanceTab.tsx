import type { ReactNode } from 'react'

import type { RunDetail } from '../../api/types'
import { StageIcon } from '../../components/status'
import { stageLabel } from '../../lib/stages'
import { Badge } from '../../components/ui/badge'
import { Card, CardBody, CardHeader } from '../../components/ui/card'
import { Callout } from '../../components/ui/feedback'
import { formatBytes, formatDateTime, formatDuration } from '../../lib/format'

/** The manifest's provenance block is free-form JSON; read it defensively. */
type Json = Record<string, unknown>

function obj(value: unknown): Json {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : {}
}

function text(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

function DefinitionList({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[12rem_1fr]">
      {items.map(([term, value]) => (
        <div key={term} className="contents">
          <dt className="text-muted">{term}</dt>
          <dd className="text-fg min-w-0 break-all">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function Mono({ children }: { children: ReactNode }) {
  return (
    <code translate="no" className="font-mono text-xs">
      {children}
    </code>
  )
}

function GitValue({ git }: { git: Json }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Mono>{text(git.commit)}</Mono>
      {git.dirty === true ? (
        <Badge
          tone="warning"
          title="Uncommitted changes: the commit alone does not identify the code"
        >
          uncommitted changes
        </Badge>
      ) : null}
    </span>
  )
}

function KeyValueTable({ data, caption }: { data: Json; caption: string }) {
  const entries = Object.entries(data)
  if (entries.length === 0) return <p className="text-muted text-sm">None recorded.</p>
  return (
    <table className="w-full text-left text-sm">
      <caption className="sr-only">{caption}</caption>
      <tbody className="divide-border divide-y">
        {entries.map(([key, value]) => (
          <tr key={key}>
            <th scope="row" className="text-muted py-2 pr-4 font-normal">
              {key}
            </th>
            <td translate="no" className="text-fg py-2 font-mono text-xs break-all">
              {text(value)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function ProvenanceTab({ run }: { run: RunDetail }) {
  const provenance = obj(run.provenance)
  const git = obj(provenance.git)
  const input = obj(provenance.input)
  const environment = obj(provenance.environment)
  const executions = [
    { index: 0, record: provenance },
    ...(run.resumes ?? []).map((record, i) => ({ index: i + 1, record: obj(record) })),
  ]

  return (
    <div className="space-y-6">
      {run.evaluation_ineligibility ? (
        <Callout tone="warning" title="Not eligible for reported results">
          {run.evaluation_ineligibility}. The evaluation harness will not score this run.
        </Callout>
      ) : (
        <Callout tone="info" title="Eligible for evaluation">
          Real audio, and every stage on disk was produced under one configuration
          {run.consistency.executions.length > 1 ? ' and one clean commit' : ''}.
        </Callout>
      )}

      <Card>
        <CardHeader title="What produced this run" />
        <CardBody>
          <DefinitionList
            items={[
              ['Run id', <Mono key="id">{run.run_id}</Mono>],
              ['Data origin', run.data_origin],
              ['Started', formatDateTime(provenance.captured_at as string | undefined)],
              ['Finished', formatDateTime(provenance.finished_at as string | undefined)],
              ['Git commit', <GitValue key="git" git={git} />],
              ['Branch', text(git.branch)],
              ['Config hash', <Mono key="cfg">{text(provenance.config_hash)}</Mono>],
              ['Package version', text(environment.package_version)],
              ['Python', `${text(environment.python)} on ${text(environment.platform)}`],
            ]}
          />
        </CardBody>
      </Card>

      {Object.keys(input).length > 0 ? (
        <Card>
          <CardHeader title="Input recording" />
          <CardBody>
            <DefinitionList
              items={[
                ['File', text(input.name)],
                ['Path', <Mono key="p">{text(input.path)}</Mono>],
                [
                  'Size',
                  typeof input.size_bytes === 'number' ? formatBytes(input.size_bytes) : '—',
                ],
                ['SHA-256', <Mono key="sha">{text(input.sha256)}</Mono>],
              ]}
            />
          </CardBody>
        </Card>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Settings"
            description="The output-affecting settings hashed into the config hash."
          />
          <CardBody>
            <KeyValueTable data={obj(provenance.settings)} caption="Settings" />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Package versions" />
          <CardBody>
            <KeyValueTable data={obj(environment.packages)} caption="Package versions" />
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Executions"
          description="A resumed run's stages can come from more than one process; each is recorded."
          actions={
            <span className="flex gap-2">
              <Badge tone={run.consistency.config ? 'success' : 'danger'}>
                {run.consistency.config ? 'One configuration' : 'Mixed configurations'}
              </Badge>
              <Badge tone={run.consistency.code ? 'success' : 'warning'}>
                {run.consistency.code ? 'Consistent code' : 'Mixed or uncommitted code'}
              </Badge>
            </span>
          }
        />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-border text-muted border-b text-xs tracking-wide uppercase">
              <tr>
                <th scope="col" className="px-5 py-3 font-medium">
                  #
                </th>
                <th scope="col" className="px-3 py-3 font-medium">
                  Started
                </th>
                <th scope="col" className="px-3 py-3 font-medium">
                  Commit
                </th>
                <th scope="col" className="px-5 py-3 font-medium">
                  Config hash
                </th>
              </tr>
            </thead>
            <tbody className="divide-border divide-y">
              {executions.map(({ index, record }) => (
                <tr key={index}>
                  <td className="px-5 py-3 tabular-nums">
                    {index}
                    {index === 0 ? <span className="text-muted"> (run)</span> : null}
                  </td>
                  <td className="text-muted px-3 py-3">
                    {formatDateTime(record.captured_at as string | undefined)}
                  </td>
                  <td className="px-3 py-3">
                    <GitValue git={obj(record.git)} />
                  </td>
                  <td className="px-5 py-3">
                    <Mono>{text(record.config_hash)}</Mono>
                    {record.allow_mixed_config === true ? (
                      <Badge tone="danger" className="ml-2">
                        mixed config allowed
                      </Badge>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <CardHeader title="Stages" />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-border text-muted border-b text-xs tracking-wide uppercase">
              <tr>
                <th scope="col" className="px-5 py-3 font-medium">
                  Stage
                </th>
                <th scope="col" className="px-3 py-3 font-medium">
                  Status
                </th>
                <th scope="col" className="px-3 py-3 text-right font-medium">
                  Time
                </th>
                <th scope="col" className="px-3 py-3 text-right font-medium">
                  Execution
                </th>
                <th scope="col" className="px-5 py-3 font-medium">
                  Counts
                </th>
              </tr>
            </thead>
            <tbody className="divide-border divide-y">
              {run.stages.map((stage) => (
                <tr key={stage.name} className="align-top">
                  <td className="text-fg px-5 py-3">{stageLabel(stage.name)}</td>
                  <td className="px-3 py-3">
                    <span className="inline-flex items-center gap-1.5">
                      <StageIcon status={stage.status} />
                      {stage.status}
                    </span>
                    {stage.error ? (
                      <p className="text-danger mt-1 max-w-sm text-xs break-words">{stage.error}</p>
                    ) : null}
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums">
                    {formatDuration(stage.seconds)}
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums">{stage.execution}</td>
                  <td translate="no" className="text-muted px-5 py-3 font-mono text-xs break-all">
                    {Object.keys(stage.counts ?? {}).length
                      ? Object.entries(stage.counts ?? {})
                          .map(
                            ([k, v]) =>
                              `${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`,
                          )
                          .join(' · ')
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
