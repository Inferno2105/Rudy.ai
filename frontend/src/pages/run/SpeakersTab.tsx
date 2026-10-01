import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, XAxis, YAxis } from 'recharts'

import { isNotFound } from '../../api/client'
import { useSpeakers } from '../../api/queries'
import type { RunDetail, StageInfo } from '../../api/types'
import { ErrorState, NotProduced } from '../../components/states'
import { SpeakerChip } from '../../components/status'
import { Card, CardBody, CardHeader } from '../../components/ui/card'
import { LoadingBlock } from '../../components/ui/feedback'
import { formatDuration, formatPercent } from '../../lib/format'
import { speakerName, speakerPalette } from '../../lib/speakers'

export function SpeakersTab({ run, stages }: { run: RunDetail; stages: StageInfo[] }) {
  const speakers = useSpeakers(run.run_id)

  const rows = useMemo(
    () =>
      Object.entries(speakers.data?.speakers ?? {})
        .map(([label, stat]) => ({ label, ...stat }))
        .sort((a, b) => b.speaking_time_sec - a.speaking_time_sec),
    [speakers.data],
  )
  const palette = useMemo(() => speakerPalette(rows.map((r) => r.label)), [rows])

  if (speakers.isPending) return <LoadingBlock label="Loading speaker statistics" lines={6} />
  if (speakers.isError) {
    return isNotFound(speakers.error) ? (
      <Card>
        <NotProduced stage="speaker_stats" stages={stages} what="speaker statistics" />
      </Card>
    ) : (
      <ErrorState error={speakers.error} onRetry={() => void speakers.refetch()} />
    )
  }

  const totals = speakers.data.totals
  const chartSummary = rows
    .map((r) => `${speakerName(r.label)} ${formatPercent(r.participation_pct)}`)
    .join(', ')

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="Share of speaking time"
          description={`${totals.num_speakers} speaker${totals.num_speakers === 1 ? '' : 's'} · ${formatDuration(totals.total_speaking_time_sec)} of speech`}
        />
        <CardBody>
          <figure>
            <div
              // An SVG chart has no single element to label; the table below carries
              // the same numbers for assistive technology.
              // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
              role="img"
              aria-label={`Bar chart of speaking time: ${chartSummary}`}
              style={{ height: Math.max(120, rows.length * 44) }}
            >
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 24 }}>
                  <CartesianGrid
                    horizontal={false}
                    strokeDasharray="3 3"
                    className="stroke-border"
                  />
                  <XAxis
                    type="number"
                    domain={[0, 100]}
                    unit="%"
                    tick={{ fontSize: 12, fill: 'currentColor' }}
                    className="text-muted"
                  />
                  <YAxis
                    type="category"
                    dataKey="label"
                    width={110}
                    tickFormatter={speakerName}
                    tick={{ fontSize: 12, fill: 'currentColor' }}
                    className="text-muted"
                  />
                  <Bar dataKey="participation_pct" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                    {rows.map((row) => (
                      <Cell key={row.label} fill={palette(row.label).hex} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <figcaption className="text-muted mt-2 text-xs">
              Percent of attributed speaking time.
              {totals.unattributed_time_sec > 0
                ? ` ${formatDuration(totals.unattributed_time_sec)} (${formatPercent(totals.unattributed_pct)}) of speech could not be attributed to any speaker and is excluded.`
                : ''}
            </figcaption>
          </figure>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Per-speaker statistics" />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-border text-muted border-b text-xs tracking-wide uppercase">
              <tr>
                <th scope="col" className="px-5 py-3 font-medium">
                  Speaker
                </th>
                <th scope="col" className="px-3 py-3 text-right font-medium">
                  Time
                </th>
                <th scope="col" className="px-3 py-3 text-right font-medium">
                  Share
                </th>
                <th scope="col" className="px-3 py-3 text-right font-medium">
                  Turns
                </th>
                <th scope="col" className="px-3 py-3 text-right font-medium">
                  Words
                </th>
                <th scope="col" className="px-5 py-3 text-right font-medium">
                  Words/min
                </th>
              </tr>
            </thead>
            <tbody className="divide-border divide-y tabular-nums">
              {rows.map((row) => (
                <tr key={row.label}>
                  <th scope="row" className="px-5 py-3 font-normal">
                    <SpeakerChip label={row.label} palette={palette} />
                  </th>
                  <td className="px-3 py-3 text-right">{formatDuration(row.speaking_time_sec)}</td>
                  <td className="px-3 py-3 text-right">{formatPercent(row.participation_pct)}</td>
                  <td className="px-3 py-3 text-right">{row.utterance_count}</td>
                  <td className="px-3 py-3 text-right">{row.word_count.toLocaleString()}</td>
                  <td className="px-5 py-3 text-right">{row.words_per_minute.toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
