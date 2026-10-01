/**
 * Test fixtures, typed against the generated API schema: if the backend's
 * response shapes change, these stop compiling instead of silently testing a
 * contract the server no longer has.
 */
import type {
  ActionItemsResponse,
  EvalReport,
  Health,
  Job,
  MetadataResponse,
  RunDetail,
  RunSummary,
  Segment,
  SpeakersResponse,
  SummaryResponse,
  TranscriptResponse,
} from '../api/types'

export const TOKEN = 'test-token-0123456789abcdef0123456789abcdef'
export const RUN_ID = '20261001-152823_batch_test_hindi'

export const health: Health = { version: '0.1.0', ok: true, problems: [] }

export const runSummaries: RunSummary[] = [
  {
    run_id: RUN_ID,
    mode: 'batch',
    status: 'completed',
    data_origin: 'real_audio',
    created_at: '2026-10-01T15:28:23',
    finished_at: '2026-10-01T15:36:20',
    git_commit: '5bc97c7aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    config_hash: '108acd72e0ed',
    audio_path: 'C:\\data\\audio\\test_hindi.wav',
  },
  {
    run_id: '20260925-181403_batch_standup',
    mode: 'batch',
    status: 'partial',
    data_origin: 'real_audio',
    created_at: '2026-09-25T18:14:03',
    finished_at: '2026-09-25T18:15:59',
    git_commit: '4bfd35c',
    config_hash: '3b9ef22c114d',
    audio_path: 'data/audio/standup.wav',
  },
  {
    run_id: '20260924-101010_live_mic',
    mode: 'live',
    status: 'completed',
    data_origin: 'real_audio',
    created_at: '2026-09-24T10:10:10',
    finished_at: '2026-09-24T10:20:10',
    git_commit: '4bfd35c',
    config_hash: '3b9ef22c114d',
    audio_path: null,
  },
]

export const stages: RunDetail['stages'] = [
  {
    name: 'transcript',
    status: 'ok',
    seconds: 44.58,
    counts: { segments: 4 },
    error: null,
    execution: 0,
  },
  { name: 'diarization', status: 'ok', seconds: 5.3, counts: {}, error: null, execution: 0 },
  { name: 'aligned', status: 'ok', seconds: 0.03, counts: {}, error: null, execution: 0 },
  { name: 'merged', status: 'ok', seconds: 0.01, counts: {}, error: null, execution: 0 },
  { name: 'tagged', status: 'ok', seconds: 0.01, counts: {}, error: null, execution: 0 },
  { name: 'speaker_stats', status: 'ok', seconds: 0.01, counts: {}, error: null, execution: 0 },
  { name: 'metadata', status: 'ok', seconds: 0.01, counts: {}, error: null, execution: 0 },
  { name: 'hinglish', status: 'ok', seconds: 13.62, counts: {}, error: null, execution: 0 },
  {
    name: 'summary',
    status: 'failed',
    seconds: 0.2,
    counts: {},
    error: 'LLMError: Ollama is not reachable at http://localhost:11434',
    execution: 0,
  },
  { name: 'action_items', status: 'skipped', seconds: 0, counts: {}, error: null, execution: 0 },
]

export function runDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    run_id: RUN_ID,
    mode: 'batch',
    status: 'partial',
    data_origin: 'real_audio',
    provenance: {
      captured_at: '2026-10-01T15:28:23',
      finished_at: '2026-10-01T15:36:20',
      git: { commit: '5bc97c7aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', branch: 'main', dirty: false },
      environment: {
        package_version: '0.1.0',
        python: '3.12.4',
        platform: 'win32',
        packages: { 'faster-whisper': '1.2.1', 'pyannote.audio': '4.0.7' },
      },
      settings: { whisper_model_size: 'large-v3', ollama_model: 'qwen2.5:7b' },
      config_hash: '108acd72e0ed',
      input: {
        path: 'C:\\data\\audio\\test_hindi.wav',
        name: 'test_hindi.wav',
        size_bytes: 1097694,
        sha256: '68a731919988a8a3498cf8724d0ed5c915c4c953fe5904b77de470fe2a7d8bf8',
      },
    },
    resumes: [],
    consistency: { executions: [0], config: true, code: true },
    evaluation_ineligibility: null,
    stages,
    extra: {},
    artifacts: ['transcript', 'diarization', 'aligned', 'merged', 'tagged', 'hinglish'],
    job: null,
    ...overrides,
  }
}

export const hinglishSegments: Segment[] = [
  {
    start: 0,
    end: 3.2,
    speaker: 'SPEAKER_00',
    language: 'Hindi',
    text: 'namaste sabko, meeting shuru karte hain',
  },
  {
    start: 3.2,
    end: 7.5,
    speaker: 'SPEAKER_01',
    language: 'English',
    text: 'Let us review the release plan first',
  },
  {
    start: 7.5,
    end: 11,
    speaker: 'SPEAKER_00',
    language: 'Code-Mixed',
    text: 'release Friday ko hoga, testing kal tak',
  },
  { start: 11, end: 12, speaker: 'UNKNOWN', language: 'English', text: 'okay' },
]

export const taggedSegments: Segment[] = [
  {
    start: 0,
    end: 3.2,
    speaker: 'SPEAKER_00',
    language: 'Hindi',
    text: 'नमस्ते सबको, मीटिंग शुरू करते हैं',
  },
  {
    start: 3.2,
    end: 7.5,
    speaker: 'SPEAKER_01',
    language: 'English',
    text: 'Let us review the release plan first',
  },
  {
    start: 7.5,
    end: 11,
    speaker: 'SPEAKER_00',
    language: 'Code-Mixed',
    text: 'release Friday को होगा, testing कल तक',
  },
  { start: 11, end: 12, speaker: 'UNKNOWN', language: 'English', text: 'okay' },
]

export const transcript: TranscriptResponse = {
  source_artifact: 'hinglish',
  segments: hinglishSegments,
}

export const summary: SummaryResponse = {
  summary: 'The team agreed to ship the release on Friday after testing.',
  highlights: ['Release planned for Friday'],
  key_decisions: ['Testing finishes tomorrow'],
}

export const actionItems: ActionItemsResponse = {
  action_items: [{ person: 'Diya', task: 'Finish testing', deadline: 'tomorrow', status: null }],
}

export const speakers: SpeakersResponse = {
  speakers: {
    SPEAKER_00: {
      speaking_time_sec: 6.7,
      participation_pct: 60.9,
      utterance_count: 2,
      word_count: 12,
      words_per_minute: 107,
      mean_utterance_sec: 3.35,
    },
    SPEAKER_01: {
      speaking_time_sec: 4.3,
      participation_pct: 39.1,
      utterance_count: 1,
      word_count: 7,
      words_per_minute: 98,
      mean_utterance_sec: 4.3,
    },
  },
  totals: {
    num_speakers: 2,
    attributed_time_sec: 11,
    unattributed_time_sec: 1,
    unattributed_pct: 8.3,
    total_speaking_time_sec: 12,
    utterance_count: 4,
    word_count: 20,
  },
}

export const metadata: MetadataResponse = {
  meeting_id: RUN_ID,
  date: '2026-10-01',
  time: '15:28',
  duration_sec: 12,
  duration_readable: '0m 12s',
  num_speakers: 2,
  languages_used: ['Code-Mixed', 'English', 'Hindi'],
  total_word_count: 20,
  segment_count: 4,
}

export function job(overrides: Partial<Job> = {}): Job {
  return {
    job_id: 'job-1',
    kind: 'batch',
    run_id: RUN_ID,
    state: 'running',
    error: null,
    submitted_at: '2026-10-01T15:28:23',
    started_at: '2026-10-01T15:28:23',
    finished_at: null,
    ...overrides,
  }
}

export const evalReport: EvalReport = {
  generated_at: '2026-10-02T09:00:00',
  git: { commit: 'abcdef1234567890', dirty: false },
  config_hashes: ['108acd72e0ed'],
  clips: [
    {
      clip_id: 'clip01',
      source: { run_id: RUN_ID, git_commit: 'abcdef1', config_hash: '108acd72e0ed' },
      asr: { wer_raw: { wer: 0.2134 }, wer_romanized: { wer: 0.1811 }, cer_raw: { cer: 0.0812 } },
      diarization: { der: 0.1523 },
    },
  ],
  aggregate: {
    num_clips: 1,
    asr: { wer_raw: { wer: 0.2134 }, wer_romanized: { wer: 0.1811 }, cer_raw: { cer: 0.0812 } },
    diarization: { der: 0.1523 },
  },
}
