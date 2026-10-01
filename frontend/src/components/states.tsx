import { FileQuestion, RefreshCw } from 'lucide-react'

import { ApiError } from '../api/client'
import type { StageInfo } from '../api/types'
import { stageLabel } from '../lib/stages'
import { Button } from './ui/button'
import { Callout, EmptyState } from './ui/feedback'

/** A failed request, with the server's own message and a retry. */
export function ErrorState({
  error,
  onRetry,
  title = 'Could not load this',
}: {
  error: unknown
  onRetry?: () => void
  title?: string
}) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : 'Unexpected error'
  return (
    <Callout tone="danger" title={title} announce="alert">
      <p>{message}</p>
      {onRetry ? (
        <Button size="sm" variant="secondary" className="mt-3" onClick={onRetry}>
          <RefreshCw aria-hidden /> Try again
        </Button>
      ) : null}
    </Callout>
  )
}

/**
 * An artifact the run has not produced. Says *why* when the manifest knows
 * (the stage failed or was skipped), so an absent summary is never mistaken
 * for an empty one.
 */
export function NotProduced({
  stage,
  stages,
  what,
}: {
  stage: string
  stages: StageInfo[]
  what: string
}) {
  const record = stages.find((s) => s.name === stage)
  let detail: string
  if (record?.status === 'failed') {
    detail = `${stageLabel(stage)} failed: ${record.error ?? 'no error recorded'}`
  } else if (record?.status === 'skipped') {
    detail = `${stageLabel(stage)} was skipped${record.error ? ` (${record.error})` : ''}.`
  } else {
    detail = `${stageLabel(stage)} has not run for this meeting yet.`
  }
  return (
    <EmptyState icon={<FileQuestion />} title={`No ${what}`}>
      {detail}
    </EmptyState>
  )
}
