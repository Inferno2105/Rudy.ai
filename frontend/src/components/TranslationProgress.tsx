import { Languages, RotateCcw } from 'lucide-react'
import { useEffect } from 'react'

import { isTranslating, useStartTranslation, useTranslation } from '../api/queries'
import type { TranslationTarget } from '../api/types'
import { TARGET_LANGUAGE } from '../lib/language'
import { Button } from './ui/button'
import { Callout } from './ui/feedback'
import { Progress } from './ui/progress'

/**
 * Everything short of a finished translation: a button to start one, its
 * progress while the server works, or why it failed. Renders nothing once the
 * translation is ready. With `autoStart`, a missing translation is requested
 * as soon as this appears (the reader has just asked to see it).
 */
export function TranslationProgress({
  runId,
  target,
  autoStart = false,
}: {
  runId: string
  target: TranslationTarget
  autoStart?: boolean
}) {
  const status = useTranslation(runId, target)
  const start = useStartTranslation(runId, target)
  const state = status.data?.state
  const language = TARGET_LANGUAGE[target]
  const { isIdle, mutate } = start

  useEffect(() => {
    if (autoStart && state === 'missing' && isIdle) mutate()
  }, [autoStart, state, isIdle, mutate])

  if (state === 'ready') return null

  if (state === 'failed' || start.isError) {
    const reason = status.data?.error ?? (start.error instanceof Error ? start.error.message : null)
    return (
      <Callout
        tone="danger"
        title={`Could not translate into ${language}`}
        announce="alert"
        className="space-y-3"
      >
        <p>
          {reason ?? 'The server did not say why.'} Check that Ollama is running on the server, then
          try again.
        </p>
        <Button size="sm" onClick={() => start.mutate()} disabled={start.isPending}>
          <RotateCcw aria-hidden /> Try again
        </Button>
      </Callout>
    )
  }

  if (state === 'missing' && !autoStart && start.isIdle) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" onClick={() => start.mutate()}>
          <Languages aria-hidden /> Translate into {language}
        </Button>
        <p className="text-muted text-xs">
          Runs on the server&apos;s language model; a few seconds per minute of meeting on a GPU,
          longer on a CPU.
        </p>
      </div>
    )
  }

  const data = status.data
  const running = isTranslating(data) && data?.state === 'running' && data.total
  return (
    <div className="space-y-2" aria-live="polite">
      <p className="text-fg flex items-center gap-2 text-sm font-medium">
        <Languages className="text-accent size-4" aria-hidden />
        {data?.state === 'queued'
          ? `Translation into ${language} is waiting for the job ahead of it…`
          : `Translating into ${language}…`}
      </p>
      <Progress
        value={running ? (data.done ?? 0) : 0}
        max={running ? (data.total ?? 1) : 1}
        label={`Translating into ${language}`}
      />
      <p className="text-muted text-xs">
        {running
          ? `${data.done ?? 0} of ${data.total} segments. You can leave this page; it carries on.`
          : 'Starting…'}
      </p>
    </div>
  )
}
