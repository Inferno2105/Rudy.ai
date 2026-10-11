import { describe, expect, it } from 'vitest'

import {
  formatBytes,
  formatClock,
  formatDuration,
  formatMetric,
  NBSP,
  plural,
  runTitle,
} from './format'
import { textLang } from './language'
import { speakerName, speakerPalette } from './speakers'
import { buildStageRows } from './stages'

describe('format', () => {
  it.each([
    [0, '0:00'],
    [59.9, '0:59'],
    [60, '1:00'],
    [3725, '1:02:05'],
  ])('formatClock(%s) = %s', (seconds, expected) => {
    expect(formatClock(seconds)).toBe(expected)
  })

  it('formats durations at each scale', () => {
    expect(formatDuration(4.25)).toBe('4.3s')
    expect(formatDuration(0.01)).toBe('<0.1s')
    expect(formatDuration(0)).toBe('0.0s')
    expect(formatDuration(75)).toBe('1m 15s')
    expect(formatDuration(3725)).toBe('1h 2m')
  })

  it('shows metric values with fixed decimals and a dash when absent', () => {
    expect(formatMetric(0.21)).toBe('0.210')
    expect(formatMetric(null)).toBe('—')
    expect(formatMetric(undefined)).toBe('—')
  })

  it('titles a run by its recording, handling Windows paths', () => {
    expect(runTitle({ run_id: 'r', mode: 'batch', audio_path: 'C:\\data\\audio\\a.wav' })).toBe(
      'a.wav',
    )
    expect(runTitle({ run_id: 'r', mode: 'live', audio_path: null })).toBe('Live session')
  })
})

describe('speakers', () => {
  it('gives a speaker the same colour regardless of order of appearance', () => {
    const a = speakerPalette(['SPEAKER_01', 'SPEAKER_00'])
    const b = speakerPalette(['SPEAKER_00', 'SPEAKER_01'])
    expect(a('SPEAKER_01')).toBe(b('SPEAKER_01'))
    expect(a('SPEAKER_00')).not.toBe(a('SPEAKER_01'))
  })

  it('renders unknown speakers neutrally and by name', () => {
    const palette = speakerPalette(['SPEAKER_00', 'UNKNOWN', null])
    expect(palette('UNKNOWN')).toBe(palette(null))
    expect(speakerName('UNKNOWN')).toBe('Unknown speaker')
    expect(speakerName('SPEAKER_G01')).toBe('Speaker G01')
  })
})

describe('textLang', () => {
  it('marks Devanagari as Hindi whatever the segment tag', () => {
    expect(textLang('नमस्ते', 'Code-Mixed')).toBe('hi')
  })

  it('marks romanized Hindi distinctly from English', () => {
    expect(textLang('namaste sabko', 'Hindi')).toBe('hi-Latn')
    expect(textLang('hello all', 'English')).toBe('en')
  })
})

describe('buildStageRows', () => {
  const ok = (name: string) => ({ name, status: 'ok' as const, seconds: 1, execution: 0 })

  it('marks the first unrecorded stage of an active batch run as running', () => {
    const rows = buildStageRows([ok('transcript')], { mode: 'batch', active: true })
    expect(rows[0]?.status).toBe('ok')
    expect(rows[1]).toMatchObject({ name: 'diarization', status: 'running' })
    expect(rows[2]?.status).toBe('pending')
  })

  it('shows nothing as running once the job is over', () => {
    const rows = buildStageRows([ok('transcript')], { mode: 'batch', active: false })
    expect(rows.filter((row) => row.status === 'running')).toEqual([])
  })

  it('lists only recorded stages for live runs', () => {
    expect(buildStageRows([ok('tagged')], { mode: 'live', active: true })).toHaveLength(1)
  })
})

describe('number formatting', () => {
  it('pluralizes counts', () => {
    expect(plural(1, 'segment')).toBe('1 segment')
    expect(plural(2, 'segment')).toBe('2 segments')
    expect(plural(1200, 'word')).toBe('1,200 words')
  })

  it('keeps a size and its unit together with a non-breaking space', () => {
    expect(formatBytes(1_097_694)).toBe(`1.0${NBSP}MB`)
    expect(formatBytes(512)).toBe(`512${NBSP}B`)
  })
})
