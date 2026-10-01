import type { StageInfo } from '../api/types'
import { formatDuration } from '../lib/format'
import { buildStageRows, STAGE_STATUS_TEXT, stageLabel } from '../lib/stages'
import { cn } from '../lib/utils'
import { StageIcon } from './status'
import { Progress } from './ui/progress'

export function StageProgress({
  stages,
  mode,
  active,
}: {
  stages: StageInfo[]
  mode: string
  active: boolean
}) {
  const rows = buildStageRows(stages, { mode, active })
  if (rows.length === 0) {
    return <p className="text-muted text-sm">No stage has completed yet.</p>
  }
  const done = rows.filter((row) => row.status === 'ok').length
  return (
    <div>
      {mode === 'batch' ? (
        <div className="mb-4">
          <p className="text-muted mb-1.5 text-xs">
            {done} of {rows.length} stages done
          </p>
          <Progress value={done} max={rows.length} label="Pipeline progress" />
        </div>
      ) : null}
      <ol className="space-y-1.5">
        {rows.map((row) => (
          <li key={row.name} className="text-sm">
            <div className="flex items-center gap-2.5">
              <StageIcon status={row.status} />
              <span
                className={cn(
                  'flex-1',
                  row.status === 'pending' ? 'text-faint' : 'text-fg',
                  row.status === 'running' && 'font-medium',
                )}
              >
                {stageLabel(row.name)}
                <span className="sr-only">: {STAGE_STATUS_TEXT[row.status] ?? row.status}</span>
              </span>
              {row.seconds != null && row.status !== 'pending' && row.status !== 'running' ? (
                <span className="text-muted text-xs tabular-nums">
                  {formatDuration(row.seconds)}
                </span>
              ) : null}
            </div>
            {row.error ? (
              <p className="text-danger mt-0.5 ml-6.5 text-xs break-words">{row.error}</p>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  )
}
