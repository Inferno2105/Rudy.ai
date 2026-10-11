import { CalendarClock, CheckSquare, Lightbulb, ListChecks, Quote, UserRound } from 'lucide-react'

import { isNotFound } from '../../api/client'
import { useActionItems, useSummary } from '../../api/queries'
import type { RunDetail, StageInfo } from '../../api/types'
import { ErrorState, NotProduced } from '../../components/states'
import { Card, CardBody, CardHeader } from '../../components/ui/card'
import { Callout, EmptyState, LoadingBlock } from '../../components/ui/feedback'

function modelName(run: RunDetail): string | null {
  const settings = run.provenance.settings as Record<string, string> | undefined
  return settings?.ollama_model ?? null
}

function BulletList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="text-muted text-sm">{empty}</p>
  return (
    <ul className="text-fg list-disc space-y-1.5 pl-5 text-sm leading-relaxed">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  )
}

function SummaryCard({ run, stages }: { run: RunDetail; stages: StageInfo[] }) {
  const summary = useSummary(run.run_id)
  return (
    <Card>
      <CardHeader title="Summary" icon={<Quote />} />
      <CardBody>
        {summary.isPending ? (
          <LoadingBlock label="Loading summary" />
        ) : summary.isError ? (
          isNotFound(summary.error) ? (
            <NotProduced stage="summary" stages={stages} what="summary" />
          ) : (
            <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
          )
        ) : (
          <div className="space-y-6">
            {summary.data.summary ? (
              <blockquote className="font-display text-fg border-accent relative border-l-2 pl-5 text-xl leading-relaxed text-balance">
                {summary.data.summary}
              </blockquote>
            ) : (
              <p className="text-muted text-sm">The model returned an empty summary.</p>
            )}
            <div className="grid gap-6 md:grid-cols-2">
              <section className="bg-subtle rounded-xl p-4">
                <h3 className="text-fg mb-2 flex items-center gap-2 text-sm font-semibold">
                  <Lightbulb className="text-warning size-4" aria-hidden /> Highlights
                </h3>
                <BulletList items={summary.data.highlights ?? []} empty="No highlights." />
              </section>
              <section className="bg-subtle rounded-xl p-4">
                <h3 className="text-fg mb-2 flex items-center gap-2 text-sm font-semibold">
                  <CheckSquare className="text-success size-4" aria-hidden /> Decisions
                </h3>
                <BulletList
                  items={summary.data.key_decisions ?? []}
                  empty="No decisions recorded."
                />
              </section>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  )
}

function ActionItemsCard({ run, stages }: { run: RunDetail; stages: StageInfo[] }) {
  const items = useActionItems(run.run_id)
  return (
    <Card>
      <CardHeader title="Action items" icon={<ListChecks />} />
      {items.isPending ? (
        <CardBody>
          <LoadingBlock label="Loading action items" lines={3} />
        </CardBody>
      ) : items.isError ? (
        <CardBody>
          {isNotFound(items.error) ? (
            <NotProduced stage="action_items" stages={stages} what="action items" />
          ) : (
            <ErrorState error={items.error} onRetry={() => void items.refetch()} />
          )}
        </CardBody>
      ) : items.data.action_items.length === 0 ? (
        <EmptyState icon={<ListChecks />} title="No action items">
          The model found no tasks assigned in this meeting.
        </EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Action items from this meeting</caption>
            <thead className="border-border text-muted border-b text-xs tracking-wide uppercase">
              <tr>
                <th scope="col" className="px-5 py-3 font-medium">
                  Task
                </th>
                <th scope="col" className="px-3 py-3 font-medium">
                  Owner
                </th>
                <th scope="col" className="px-5 py-3 font-medium">
                  Deadline
                </th>
              </tr>
            </thead>
            <tbody className="divide-border divide-y">
              {items.data.action_items.map((item, index) => (
                <tr key={index} className="hover:bg-subtle transition-colors">
                  <td className="text-fg px-5 py-3 font-medium">{item.task || '—'}</td>
                  <td className="px-3 py-3">
                    <span className="bg-subtle text-fg inline-flex items-center gap-1.5 rounded-full py-0.5 pr-2.5 pl-1 text-xs">
                      <UserRound className="text-accent size-4" aria-hidden />
                      {item.person || 'Unassigned'}
                    </span>
                  </td>
                  <td className="text-muted px-5 py-3">
                    <span className="inline-flex items-center gap-1.5 text-xs">
                      <CalendarClock className="size-4" aria-hidden />
                      {item.deadline || 'None given'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

export function SummaryTab({ run, stages }: { run: RunDetail; stages: StageInfo[] }) {
  const model = modelName(run)
  return (
    <div className="space-y-6">
      <Callout tone="info">
        Generated by a language model{model ? ` (${model})` : ''} from the transcript. Check it
        against the transcript before relying on it.
      </Callout>
      <SummaryCard run={run} stages={stages} />
      <ActionItemsCard run={run} stages={stages} />
    </div>
  )
}
