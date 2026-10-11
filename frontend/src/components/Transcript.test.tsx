import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Segment } from '../api/types'
import { speakerPalette } from '../lib/speakers'
import { Transcript, VIRTUALIZE_ABOVE } from './Transcript'

function segments(count: number): Segment[] {
  return Array.from({ length: count }, (_, i) => ({
    start: i * 2,
    end: i * 2 + 2,
    speaker: `SPEAKER_0${i % 2}`,
    language: 'English',
    text: `line ${i}`,
  }))
}

describe('Transcript', () => {
  it('renders every segment of a short meeting', () => {
    const list = segments(VIRTUALIZE_ABOVE)
    render(<Transcript segments={list} palette={speakerPalette([])} />)
    expect(within(screen.getByRole('list')).getAllByRole('listitem')).toHaveLength(list.length)
  })

  // The virtualized case (more than VIRTUALIZE_ABOVE segments) needs real layout and
  // is covered by the Playwright test 'a long transcript renders only the rows near
  // the viewport' (frontend/e2e/meeting.spec.ts).
})
