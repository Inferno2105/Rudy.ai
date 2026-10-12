/**
 * Friendly names for the generated API types. Nothing here is hand-written
 * shape: every type is an alias into `schema.d.ts`, which is generated from
 * the backend's OpenAPI schema (`npm run gen:api`).
 */
import type { components, operations } from './schema'

type Schemas = components['schemas']

export type Health = Schemas['Health']
export type RunSummary = Schemas['RunSummary']
export type RunDetail = Schemas['RunDetail']
export type StageInfo = Schemas['StageInfo']
export type Consistency = Schemas['Consistency']
export type Segment = Schemas['Segment']
export type TranscriptResponse = Schemas['TranscriptResponse']
export type SummaryResponse = Schemas['SummaryResponse']
export type ActionItem = Schemas['ActionItem']
export type ActionItemsResponse = Schemas['ActionItemsResponse']
export type SpeakersResponse = Schemas['SpeakersResponse']
export type SpeakerStat = Schemas['SpeakerStat']
export type MetadataResponse = Schemas['MetadataResponse']
export type Job = Schemas['Job']
export type JobAccepted = Schemas['JobAccepted']
export type AudioFile = Schemas['AudioFile']
export type UploadResult = Schemas['UploadResult']
export type InputDevice = Schemas['InputDevice']
export type SearchHit = Schemas['SearchHit']
export type WaveformResponse = Schemas['WaveformResponse']
export type EvalReport = Schemas['EvalReport']
export type ClipReport = Schemas['ClipReport']
export type AggregateReport = Schemas['AggregateReport']
export type ManifestEvent = Schemas['ManifestEvent']
export type SegmentsEvent = Schemas['SegmentsEvent']
export type EndEvent = Schemas['EndEvent']
export type TranslationStatus = Schemas['TranslationStatus']
export type TranslationTarget = TranslationStatus['target']

/** The artifact names the backend accepts for `/runs/{id}/artifacts/{name}`. */
export type ArtifactName =
  operations['get_raw_artifact_api_runs__run_id__artifacts__name__get']['parameters']['path']['name']

export const ACTIVE_JOB_STATES: ReadonlySet<Job['state']> = new Set([
  'queued',
  'running',
  'stopping',
])

export function isJobActive(job: Job | null | undefined): boolean {
  return job != null && ACTIVE_JOB_STATES.has(job.state)
}
