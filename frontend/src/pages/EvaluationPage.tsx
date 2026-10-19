import { BarChart3 } from 'lucide-react'
import { Link } from 'react-router'

import { isNotFound } from '../api/client'
import { useEvalReport } from '../api/queries'
import type { AggregateReport, ClipReport, EvalReport } from '../api/types'
import { PageHeader } from '../components/AppShell'
import { CountUp } from '../components/motion'
import { Badge } from '../components/ui/badge'
import { ErrorState } from '../components/states'
import { Card, CardBody, CardHeader } from '../components/ui/card'
import { Callout, EmptyState, LoadingBlock } from '../components/ui/feedback'
import { formatCount, formatDateTime, formatMetric, plural, shortHash } from '../lib/format'
import { useDocumentTitle } from '../lib/utils'

type Families = AggregateReport | ClipReport

interface Metric {
  key: string
  /** Dotted path in the report, as the harness names it in `ci95`. */
  path: string
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
    path: 'asr.wer_raw.wer',
    label: 'WER (raw script)',
    family: 'ASR',
    better: 'lower',
    read: (r) => r.asr?.wer_raw?.wer,
  },
  {
    key: 'wer_rom',
    path: 'asr.wer_romanized.wer',
    label: 'WER (romanized)',
    family: 'ASR',
    better: 'lower',
    read: (r) => r.asr?.wer_romanized?.wer,
  },
  {
    key: 'cer_raw',
    path: 'asr.cer_raw.cer',
    label: 'CER (raw script)',
    family: 'ASR',
    better: 'lower',
    read: (r) => r.asr?.cer_raw?.cer,
  },
  {
    key: 'wer_nf',
    path: 'asr.wer_raw_no_fillers.wer',
    label: 'WER without fillers',
    family: 'ASR',
    better: 'lower',
    read: (r) => r.asr?.wer_raw_no_fillers?.wer,
  },
  {
    key: 'der',
    path: 'diarization.der',
    label: 'DER',
    family: 'Diarization',
    better: 'lower',
    read: (r) => r.diarization?.der,
  },
  {
    key: 'der_nc',
    path: 'diarization.no_collar.der',
    label: 'DER (no collar)',
    family: 'Diarization',
    better: 'lower',
    read: (r) => r.diarization?.no_collar?.der,
  },
  {
    key: 'langid',
    path: 'language_id.accuracy',
    label: 'Language-ID accuracy',
    family: 'Language ID',
    better: 'higher',
    read: (r) => r.language_id?.accuracy,
  },
  {
    key: 'unattributed',
    path: 'attribution.unattributed_share',
    label: 'Unattributed speech',
    family: 'Diarization',
    better: 'lower',
    read: (r) => r.attribution?.unattributed_share,
  },
  {
    key: 'rougeL',
    path: 'summary.rougeL_f',
    label: 'ROUGE-L F',
    family: 'Summary',
    better: 'higher',
    read: (r) => r.summary?.rougeL_f,
  },
  {
    key: 'rubric',
    path: 'summary_rubric.mean',
    label: 'Summary rubric (1–3)',
    family: 'Summary',
    better: 'higher',
    read: (r) => r.summary_rubric?.mean,
  },
  {
    key: 'ai_f1',
    path: 'action_items.f1',
    label: 'Action-item F1',
    family: 'Action items',
    better: 'higher',
    read: (r) => r.action_items?.f1,
  },
  {
    key: 'registry',
    path: 'registry.identity_accuracy',
    label: 'Speaker identity accuracy',
    family: 'Speaker registry',
    better: 'higher',
    read: (r) => r.registry?.identity_accuracy,
  },
  {
    key: 'rtf',
    path: 'system.realtime_factor',
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
      {present.map((metric) => {
        const ci = aggregate.ci95?.[metric.path]
        return (
          <Card key={metric.key} className="px-5 py-4">
            <p className="text-muted text-xs font-medium tracking-wide uppercase">
              {metric.family}
            </p>
            <p className="text-fg mt-1 text-sm">{metric.label}</p>
            <p className="text-brand font-display mt-2 text-3xl font-semibold tabular-nums">
              <CountUp value={metric.read(aggregate) ?? 0} digits={3} />
            </p>
            <p className="text-faint mt-1 text-xs">
              {metric.better} is better
              {ci ? (
                <>
                  {' '}
                  · 95% CI{' '}
                  <span className="tabular-nums">
                    {formatMetric(ci[0])}–{formatMetric(ci[1])}
                  </span>
                </>
              ) : null}
            </p>
          </Card>
        )
      })}
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
              <th scope="row" className="text-fg px-5 py-3 font-medium whitespace-nowrap">
                <span translate="no">{clip.clip_id}</span>
                {clip.source?.dataset && clip.source.dataset !== 'recorded' ? (
                  <Badge className="ml-2" translate="no">
                    {clip.source.dataset}
                  </Badge>
                ) : clip.source?.data_origin === 'synthetic' ? (
                  <Badge className="ml-2">synthetic</Badge>
                ) : null}
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
  const real = report.aggregate.num_clips
  const synthetic = report.aggregate_synthetic?.num_clips ?? 0
  const external = Object.entries(report.aggregate_external ?? {})
  return (
    <div className="space-y-6">
      <p className="text-muted text-sm">
        {plural(real, 'own recording')}
        {synthetic ? ` · ${plural(synthetic, 'synthetic clip')}` : ''}
        {external.map(([name, agg]) => ` · ${formatCount(agg.num_clips)} ${name}`).join('')} ·
        generated {formatDateTime(report.generated_at)}
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
          Recorded for this project
        </h2>
        {real ? (
          <MetricCards aggregate={report.aggregate} />
        ) : (
          <p className="text-muted text-sm">
            None of this project&rsquo;s recordings is scored yet.
          </p>
        )}
        <p className="text-muted mt-2 text-xs">
          Plain per-clip means; a clip without a reference for a family is left out of that family
          rather than counted as zero.
        </p>
      </section>

      {report.aggregate_synthetic ? (
        <section aria-labelledby="synthetic-heading">
          <h2 id="synthetic-heading" className="text-fg mb-1 text-lg font-semibold">
            Synthetic speech
          </h2>
          <p className="text-muted mb-3 text-sm">
            Clips voiced by text-to-speech, scored the same way but reported separately: they are
            never mixed into the real-recording numbers.
          </p>
          <MetricCards aggregate={report.aggregate_synthetic} />
        </section>
      ) : null}

      {external.map(([name, agg]) => (
        <section key={name} aria-labelledby={`set-${name}`}>
          <h2 id={`set-${name}`} className="text-fg mb-1 text-lg font-semibold" translate="no">
            {name}
          </h2>
          <p className="text-muted mb-3 text-sm">
            A published corpus, reported on its own. DER without a collar is the figure to compare
            with that corpus&rsquo;s published results.
          </p>
          <MetricCards aggregate={agg} />
        </section>
      ))}

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
        eyebrow="Research"
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
