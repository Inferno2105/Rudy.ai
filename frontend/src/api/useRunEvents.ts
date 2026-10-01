import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useReducer } from 'react'

import { keys } from './queries'
import { followRunEvents, type RunEvent, type StreamStatus } from './sse'
import type { Job, ManifestEvent, Segment } from './types'

export interface RunEventsState {
  status: StreamStatus | 'idle'
  detail?: string | undefined
  manifest: ManifestEvent | null
  segments: Segment[]
  job: Job | null
  ended: boolean
}

type Action =
  | { kind: 'reset' }
  | { kind: 'status'; status: StreamStatus; detail?: string | undefined }
  | { kind: 'event'; event: RunEvent }

export const initialRunEvents: RunEventsState = {
  status: 'idle',
  manifest: null,
  segments: [],
  job: null,
  ended: false,
}

export function runEventsReducer(state: RunEventsState, action: Action): RunEventsState {
  switch (action.kind) {
    case 'reset':
      return initialRunEvents
    case 'status':
      return { ...state, status: action.status, detail: action.detail }
    case 'event': {
      const { event } = action
      switch (event.type) {
        case 'manifest':
          return { ...state, manifest: event.data }
        case 'segments': {
          // Splice by index: after a reconnect the server replays from 0, and
          // this keeps the list identical to the server's instead of duplicating.
          const { start_index: start, segments } = event.data
          return { ...state, segments: [...state.segments.slice(0, start), ...segments] }
        }
        case 'job':
          return { ...state, job: event.data }
        case 'end':
          return { ...state, ended: true }
      }
    }
  }
  return state
}

/**
 * Follow a run's live progress while `enabled`. When the stream ends, every
 * cached view of the run is invalidated so artifacts produced during the run
 * (summary, speakers, ...) load without a manual refresh.
 */
export function useRunEvents(runId: string, enabled: boolean): RunEventsState {
  const [state, dispatch] = useReducer(runEventsReducer, initialRunEvents)
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!enabled) return
    dispatch({ kind: 'reset' })
    const controller = new AbortController()
    void followRunEvents(runId, {
      signal: controller.signal,
      onStatus: (status, detail) => dispatch({ kind: 'status', status, detail }),
      onEvent: (event) => {
        dispatch({ kind: 'event', event })
        if (event.type === 'end') {
          void queryClient.invalidateQueries({ queryKey: keys.run(runId) })
          void queryClient.invalidateQueries({ queryKey: keys.allRuns })
          void queryClient.invalidateQueries({ queryKey: keys.currentJob })
        }
      },
    })
    return () => controller.abort()
  }, [runId, enabled, queryClient])

  return state
}
