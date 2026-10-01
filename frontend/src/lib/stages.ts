import type { StageInfo } from '../api/types'

/** Human names for pipeline stages (the manifest records artifact names). */
export const STAGE_LABELS: Record<string, string> = {
  transcript: 'Transcription',
  diarization: 'Speaker diarization',
  aligned: 'Alignment',
  merged: 'Turn merging',
  tagged: 'Language tagging',
  hinglish: 'Hinglish normalization',
  summary: 'Summary',
  action_items: 'Action items',
  speaker_stats: 'Speaker statistics',
  metadata: 'Meeting metadata',
}

/**
 * Execution order of batch stages (the backend's `BATCH_STAGES`), used to
 * list stages that have not run yet. Unknown stages are appended as recorded.
 */
export const BATCH_STAGE_ORDER = [
  'transcript',
  'diarization',
  'aligned',
  'merged',
  'tagged',
  'speaker_stats',
  'metadata',
  'hinglish',
  'summary',
  'action_items',
]

export function stageLabel(name: string): string {
  return STAGE_LABELS[name] ?? name
}

export type DisplayStatus = StageInfo['status'] | 'pending' | 'running'

export const STAGE_STATUS_TEXT: Record<string, string> = {
  ok: 'done',
  failed: 'failed',
  skipped: 'skipped',
  running: 'running',
  pending: 'pending',
}

export interface StageRow {
  name: string
  status: DisplayStatus
  seconds?: number | undefined
  error?: string | null | undefined
}

/**
 * Per-stage rows for a progress view. For a batch run with an active job,
 * every expected stage is listed and the first one without a record is shown
 * as running -- the orchestrator runs stages strictly in order, so that is
 * the stage currently executing.
 */
export function buildStageRows(
  stages: StageInfo[],
  { mode, active }: { mode: string; active: boolean },
): StageRow[] {
  const recorded = new Map(stages.map((stage) => [stage.name, stage]))
  const names =
    mode === 'batch'
      ? [
          ...BATCH_STAGE_ORDER,
          ...stages.map((s) => s.name).filter((n) => !BATCH_STAGE_ORDER.includes(n)),
        ]
      : stages.map((s) => s.name)

  let runningAssigned = false
  return names.map((name) => {
    const stage = recorded.get(name)
    if (stage) return { name, status: stage.status, seconds: stage.seconds, error: stage.error }
    if (active && !runningAssigned) {
      runningAssigned = true
      return { name, status: 'running' }
    }
    return { name, status: 'pending' }
  })
}
