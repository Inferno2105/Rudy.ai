/** Microphone levels (0 silence .. 1 full scale) and what they mean for a speaker. */

/** Readings near full scale: the input is clipping. */
export const CLIPPING = 0.92
/** Below this the microphone is hearing little more than room noise. */
export const QUIET = 0.18

/** A plain-language reading of the last couple of seconds, for a microphone check. */
export function levelHint(history: number[]): { tone: 'muted' | 'ok' | 'warn'; text: string } {
  const recent = history.slice(-24)
  if (recent.length < 6) return { tone: 'muted', text: 'Listening to the microphone…' }
  const peak = Math.max(...recent)
  if (peak >= CLIPPING) {
    return { tone: 'warn', text: 'Very loud: move the microphone a little further away.' }
  }
  if (peak < QUIET) {
    return { tone: 'warn', text: 'Hardly anything is coming through. Say a few words to check.' }
  }
  return { tone: 'ok', text: 'The microphone is picking you up.' }
}
