import { useEffect, useState } from 'react'

import { followMicLevel } from './sse'

/** How many recent readings the meter draws (about four seconds). */
export const LEVEL_HISTORY = 48

/**
 * The server microphone's recent loudness while `enabled`: the newest
 * reading last, each 0 (silence) to 1 (full scale).
 */
export function useMicLevel(enabled: boolean): number[] {
  const [history, setHistory] = useState<number[]>([])

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    void followMicLevel({
      signal: controller.signal,
      onLevel: (level) =>
        setHistory((previous) => [...previous.slice(-(LEVEL_HISTORY - 1)), level]),
    })
    return () => controller.abort()
  }, [enabled])

  return enabled ? history : []
}
