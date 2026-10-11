import { BarChart3 } from 'lucide-react'
import { Link } from 'react-router'

import { isNotFound } from '../api/client'
import { useEvalReport } from '../api/queries'
import type { AggregateReport, ClipReport, EvalReport } from '../api/types'
import { PageHeader } from '../components/AppShell'
import { ErrorState } from '../components/states'
import { Card, CardBody, CardHeader } from '../components/ui/card'
import { Callout, EmptyState, LoadingBlock } from '../components/ui/feedback'
import { formatDateTime, formatMetric, shortHash } from '../lib/format'
import { useDocumentTitle } from '../lib/utils'

type Families = AggregateReport | ClipReport

interface Metric {
  key: string
  label: string
  /** Where the value lives in a clip report / the aggregate. */
  read: (report: Families) => number | null | undefined
  better: 'lower' | 'higher'
  family: string
}

/**
 * The metrics the dashboard shows, by family. Values are read exactly as the
 * harness wrote them; nothing is recomputed in the browser.
 */
const METRICS: Metric[] = [
  {
    key: 'wer_raw',
    label: 'WER (raw script)',
    family: 'ASR',
    better: 'lower',
    read: (r) => r.asr?.wer_raw?.wer,
  },
  {
    key: 'wer_rom',
    label: 'WER (romanized)',
    family: 'ASR',
    better: 'lower',
    read: (r) => r.asr?.wer_romanized?.wer,
  },
  {
    key: 'cer_raw',
    label: 'CER (raw script)',
    family: 'ASR',
    better: 'lower',
    read: (r) => r.asr?.cer_raw?.cer,
  },
  {
    key: 'der',
    label: 'DER',
    family: 'Diarization',
    better: 'lower',
    read: (r) => r.diarization?.der,
  },
  {
    key: 'langid',
    label: 'Language-ID accuracy',
    family: 'Language ID',
    better: 'higher',
    read: (r) => r.language_id?.accuracy,
  },
  {
    key: 'rougeL',
    label: 'ROUGE-L F',
    family: 'Summary',
    better: 'higher',
    read: (r) => r.summary?.rougeL_f,
  },
  {
    key: 'ai_f1',
    label: 'Action-item F1',
    family: 'Action items',
    better: 'higher',
    read: (r) => r.action_items?.f1,
  },
  {
    key: 'registry',
    label: 'Speaker identity accuracy',
    family: 'Speaker registry',
    better: 'higher',
    read: (r) => r.registry?.identity_accuracy,
  },
  {
    key: 'rtf',
    label: 'Real-time factor',
    family: 'System',
    better: 'lower',
    read: (r) => {
      const value = r.system?.realtime_factor
      return typeof value === 'number' ? value : null
    },
  },
]

function MetricCards({ aggregate }: { aggregate: AggregateReport }) {
  const present = METRICS.filter((metric) => metric.read(aggregate) != null)
  if (present.length === 0) {
    return <p className="text-muted text-sm">No metric family had data for any clip.</p>
  }
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {present.map((metric) => (
        <Card key={metric.key} className="px-5 py-4">
          <p className="text-muted text-xs font-medium tracking-wide uppercase">{metric.family}</p>
          <p className="text-fg mt-1 text-sm">{metric.label}</p>
          <p className="text-fg mt-2 font-mono text-2xl font-semibold tabular-nums">
            {formatMetric(metric.read(aggregate))}
          </p>
          <p className="text-faint mt-1 text-xs">{metric.better} is better</p>
        </Card>
      ))}
    </div>
  )
}

function ClipTable({ clips }: { clips: ClipReport[] }) {
  const columns = METRICS.filter((metric) => clips.some((clip) => metric.read(clip) != null))
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Metrics for each evaluated clip</caption>
        <thead className="border-border text-muted border-b text-xs tracking-wide uppercase">
          <tr>
            <th scope="col" className="px-5 py-3 font-medium">
              Clip
            </th>
            {columns.map((metric) => (
              <th
                key={metric.key}
                scope="col"
                className="px-3 py-3 text-right font-medium whitespace-nowrap"
              >
                {metric.label}
              </th>
            ))}
            <th scope="col" className="px-5 py-3 font-medium">
              Scored run
            </th>
          </tr>
        </thead>
        <tbody className="divide-border divide-y">
          {clips.map((clip) => (
            <tr key={clip.clip_id}>
              <th scope="row" translate="no" className="text-fg px-5 py-3 font-medium">
                {clip.clip_id}
              </th>
              {columns.map((metric) => (
                <td
                  key={metric.key}
                  className="px-3 py-3 text-right font-mono text-xs tabular-nums"
                >
                  {formatMetric(metric.read(clip))}
                </td>
              ))}
              <td className="px-5 py-3">
                {clip.source ? (
                  <>
                    <Link
                      to={`/runs/${encodeURIComponent(clip.source.run_id)}?tab=provenance`}
                      translate="no"
                      className="text-accent font-mono text-xs hover:underline"
                    >
                      {clip.source.run_id}
                    </Link>
                    {/* Shown, not hidden in a tooltip: this is what makes the row's numbers traceable. */}
                    <span translate="no" className="text-faint block font-mono text-xs">
                      commit {shortHash(clip.source.git_commit)}
                      {clip.source.git_dirty ? ' (dirty)' : ''} · config{' '}
                      {shortHash(clip.source.config_hash)}
                    </span>
                  </>
                ) : (
                  <span className="text-faint text-xs">not recorded</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Report({ report }: { report: EvalReport }) {
  const configHashes = report.config_hashes ?? []
  const git = report.git as { commit?: string; dirty?: boolean } | null | undefined
  return (
    <div className="space-y-6">
      <p className="text-muted text-sm">
        {report.aggregate.num_clips} clip{report.aggregate.num_clips === 1 ? '' : 's'} · generated{' '}
        {formatDateTime(report.generated_at)}
        {git?.commit ? (
          <>
            {' '}
            from commit{' '}
            <code translate="no" className="font-mono text-xs">
              {shortHash(git.commit)}
            </code>
            {git.dirty ? ' (with uncommitted changes)' : ''}
          </>
        ) : null}
      </p>

      {configHashes.length > 1 ? (
        <Callout tone="warning" title="These results mix configurations">
          The scored runs used {configHashes.length} different configurations (
          {configHashes.join(', ')}). An aggregate across them does not describe any single system.
        </Callout>
      ) : null}
      {report.clips.some((clip) => !clip.source) ? (
        <Callout tone="warning" title="Some clips do not record which run they came from">
          This report predates run tracking. Re-run{' '}
          <code translate="no" className="font-mono">
            meeting-assistant eval
          </code>{' '}
          so every number traces back to its run.
        </Callout>
      ) : null}

      <section aria-labelledby="aggregate-heading">
        <h2 id="aggregate-heading" className="text-fg mb-3 text-lg font-semibold">
          Mean across clips
        </h2>
        <MetricCards aggregate={report.aggregate} />
        <p className="text-muted mt-2 text-xs">
          Plain per-clip means; a clip without a reference for a family is left out of that family
          rather than counted as zero.
        </p>
      </section>

      <Card>
        <CardHeader
          title="Per clip"
          description="Each row links to the run it was scored against."
        />
        <ClipTable clips={report.clips} />
      </Card>
    </div>
  )
}

export function EvaluationPage() {
  useDocumentTitle('Evaluation')
  const report = useEvalReport()
  return (
    <>
      <PageHeader
        title="Evaluation"
        description="Results of the latest evaluation pass over the labelled dataset."
      />
      {report.isPending ? (
        <LoadingBlock label="Loading the evaluation report" lines={6} />
      ) : report.isError ? (
        isNotFound(report.error) ? (
          <Card>
            <CardBody>
              <EmptyState icon={<BarChart3 />} title="No evaluation report yet">
                <p>
                  Label clips under{' '}
                  <code translate="no" className="font-mono">
                    data/eval/references/
                  </code>{' '}
                  as described in{' '}
                  <code translate="no" className="font-mono">
                    docs/evaluation.md
                  </code>
                  , process each recording, then run{' '}
                  <code translate="no" className="font-mono">
                    meeting-assistant eval
                  </code>
                  . The report appears here.
                </p>
              </EmptyState>
            </CardBody>
          </Card>
        ) : (
          <ErrorState error={report.error} onRetry={() => void report.refetch()} />
        )
      ) : (
        <Report report={report.data} />
      )}
    </>
  )
}
