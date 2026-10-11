/**
 * Server state, via TanStack Query. One hook per resource; components never
 * call the client directly, so caching, polling and invalidation rules live
 * in one place.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError, fetchArtifact, unwrap } from './client'
import type { ArtifactName } from './types'

export const keys = {
  health: ['health'] as const,
  auth: ['auth'] as const,
  runs: (filters: RunFilters) => ['runs', filters] as const,
  allRuns: ['runs'] as const,
  run: (runId: string) => ['run', runId] as const,
  runPart: (runId: string, part: string) => ['run', runId, part] as const,
  audio: ['audio'] as const,
  devices: ['devices'] as const,
  currentJob: ['jobs', 'current'] as const,
  evalReport: ['eval', 'report'] as const,
}

/** Never retry a client error: a 404 is an answer ("not produced"), not a blip. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
  return failureCount < 2
}

// ---------------------------------------------------------------------------
// Accounts
// ---------------------------------------------------------------------------
export function useAuthStatus() {
  return useQuery({
    queryKey: keys.auth,
    queryFn: ({ signal }) => unwrap(api.GET('/api/auth/status', { signal })),
    staleTime: 60_000,
  })
}

/** After signing in or out, everything cached belongs to the previous state. */
function useResetAfterAuth() {
  const client = useQueryClient()
  return () => {
    client.removeQueries({ predicate: (query) => query.queryKey[0] !== 'health' })
  }
}

export function useLogin() {
  const reset = useResetAfterAuth()
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      unwrap(api.POST('/api/auth/login', { body })),
    onSuccess: reset,
  })
}

export function useSetup() {
  const reset = useResetAfterAuth()
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      unwrap(api.POST('/api/auth/setup', { body })),
    onSuccess: reset,
  })
}

/** Create another account (not the first) and sign in as it. */
export function useRegister() {
  const reset = useResetAfterAuth()
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      unwrap(api.POST('/api/auth/register', { body })),
    onSuccess: reset,
  })
}

export function useLogout() {
  const reset = useResetAfterAuth()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/auth/logout')),
    onSettled: reset,
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      unwrap(api.POST('/api/auth/password', { body })),
  })
}

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: ({ signal }) => unwrap(api.GET('/api/health', { signal })),
    refetchInterval: 15_000,
  })
}

export interface RunFilters {
  status?: string | undefined
  mode?: string | undefined
}

export function useRuns(filters: RunFilters) {
  return useQuery({
    queryKey: keys.runs(filters),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/runs', {
          params: { query: { status: filters.status ?? null, mode: filters.mode ?? null } },
          signal,
        }),
      ),
    placeholderData: keepPreviousData,
  })
}

export function useRun(runId: string, options: { poll?: boolean } = {}) {
  return useQuery({
    queryKey: keys.run(runId),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/runs/{run_id}', { params: { path: { run_id: runId } }, signal })),
    refetchInterval: options.poll ? 2_000 : false,
  })
}

const runPath = (runId: string) => ({ params: { path: { run_id: runId } } })

export function useTranscript(runId: string) {
  return useQuery({
    queryKey: keys.runPart(runId, 'transcript'),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/runs/{run_id}/transcript', { ...runPath(runId), signal })),
  })
}

export function useSummary(runId: string) {
  return useQuery({
    queryKey: keys.runPart(runId, 'summary'),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/runs/{run_id}/summary', { ...runPath(runId), signal })),
  })
}

export function useActionItems(runId: string) {
  return useQuery({
    queryKey: keys.runPart(runId, 'action-items'),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/runs/{run_id}/action-items', { ...runPath(runId), signal })),
  })
}

export function useSpeakers(runId: string) {
  return useQuery({
    queryKey: keys.runPart(runId, 'speakers'),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/runs/{run_id}/speakers', { ...runPath(runId), signal })),
  })
}

export function useMetadata(runId: string) {
  return useQuery({
    queryKey: keys.runPart(runId, 'metadata'),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/runs/{run_id}/metadata', { ...runPath(runId), signal })),
  })
}

export function useArtifact(runId: string, name: ArtifactName, enabled = true) {
  return useQuery({
    queryKey: keys.runPart(runId, `artifact:${name}`),
    queryFn: () => fetchArtifact(runId, name),
    enabled,
    staleTime: Infinity, // artifacts are written once per execution
  })
}

export function useAudioFiles() {
  return useQuery({
    queryKey: keys.audio,
    queryFn: ({ signal }) => unwrap(api.GET('/api/audio', { signal })),
  })
}

export function useDevices() {
  return useQuery({
    queryKey: keys.devices,
    queryFn: ({ signal }) => unwrap(api.GET('/api/devices', { signal })),
    staleTime: 60_000,
  })
}

export function useCurrentJob() {
  return useQuery({
    queryKey: keys.currentJob,
    queryFn: ({ signal }) => unwrap(api.GET('/api/jobs/current', { signal })),
    refetchInterval: 3_000,
  })
}

export function useEvalReport() {
  return useQuery({
    queryKey: keys.evalReport,
    queryFn: ({ signal }) => unwrap(api.GET('/api/eval/report', { signal })),
  })
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------
export function useStartBatch() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { audio: string; num_speakers: number | null }) =>
      unwrap(api.POST('/api/runs/batch', { body })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.currentJob })
    },
  })
}

export function useResume(runId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { force_stage: string | null; allow_mixed_config: boolean }) =>
      unwrap(api.POST('/api/runs/{run_id}/resume', { ...runPath(runId), body })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.run(runId) })
      void client.invalidateQueries({ queryKey: keys.currentJob })
    },
  })
}

export function useStartLive() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      num_speakers: number | null
      device: number | null
      use_registry: boolean
    }) => unwrap(api.POST('/api/live/start', { body })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.currentJob })
    },
  })
}

export function useStopLive() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/live/stop')),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.currentJob })
    },
  })
}

export function useRebuildIndex() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/index/rebuild')),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.allRuns })
    },
  })
}
