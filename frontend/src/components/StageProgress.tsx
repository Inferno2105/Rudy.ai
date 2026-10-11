import { AnimatePresence, motion } from 'motion/react'

import type { StageInfo } from '../api/types'
import { formatDuration } from '../lib/format'
import { buildStageRows, STAGE_STATUS_TEXT, stageLabel } from '../lib/stages'
import { EASE_OUT } from '../lib/easing'
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
        <div className="mb-5">
          <p className="text-muted mb-2 flex justify-between text-xs">
            <span>
              {done} of {rows.length} stages done
            </span>
            <span className="tabular-nums">{Math.round((done / rows.length) * 100)}%</span>
          </p>
          <Progress value={done} max={rows.length} label="Pipeline progress" />
        </div>
      ) : null}
      <ol className="grid gap-1.5 sm:grid-cols-2">
        {rows.map((row, index) => (
          <motion.li
            key={row.name}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3, delay: index * 0.03, ease: EASE_OUT }}
            className={cn(
              'relative overflow-hidden rounded-lg px-3 py-2 text-sm',
              row.status === 'running' && 'bg-accent-soft ring-accent/25 ring-1 ring-inset',
            )}
          >
            {row.status === 'running' ? (
              // A light sweep across the stage that is working right now.
              <span
                aria-hidden
                className="animate-shimmer absolute inset-0 bg-[linear-gradient(90deg,transparent,color-mix(in_oklch,var(--color-accent)_18%,transparent),transparent)] bg-[length:200%_100%]"
              />
            ) : null}
            <div className="relative flex items-center gap-2.5">
              <AnimatePresence mode="popLayout" initial={false}>
                <motion.span
                  key={row.status}
                  initial={{ scale: 0.4, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0.4, opacity: 0 }}
                  transition={{ type: 'spring', stiffness: 500, damping: 26 }}
                  className="inline-flex"
                >
                  <StageIcon status={row.status} />
                </motion.span>
              </AnimatePresence>
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
                <span className="text-faint font-mono text-xs tabular-nums">
                  {formatDuration(row.seconds)}
                </span>
              ) : null}
            </div>
            {row.error ? (
              <p className="text-danger relative mt-0.5 ml-6.5 text-xs break-words">{row.error}</p>
            ) : null}
          </motion.li>
        ))}
      </ol>
    </div>
  )
}
