import type { RunDetail, Segment } from '../api/types'
import { basename } from './format'

/** The recording's file name, or a readable fallback for live sessions. */
export function runSourceName(run: RunDetail): string {
  const input = run.provenance.input as { name?: string; path?: string } | undefined
  return input?.name ?? basename(input?.path) ?? (run.mode === 'live' ? 'Live session' : run.run_id)
}

export function matchesQuery(segment: Segment, query: string): boolean {
  return !query || segment.text.toLocaleLowerCase().includes(query.toLocaleLowerCase())
}
