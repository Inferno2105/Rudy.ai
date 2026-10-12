/**
 * Server-sent events over `fetch`.
 *
 * The run event stream is read with `fetch` rather than `EventSource` for
 * control: an explicit abort on unmount, a backoff we choose, and a clean stop
 * on the server's `end` event (which `EventSource` would treat as a dropped
 * connection and retry forever). The parser follows the WHATWG rules that
 * matter in practice: `\n`, `\r\n` or `\r` line endings (including a `\r\n`
 * split across two network chunks), multi-line `data`, comment lines (the
 * server's keepalives), and dispatch on a blank line.
 */
import { apiUrl, noteStatus } from './client'
import type { EndEvent, Job, ManifestEvent, SegmentsEvent } from './types'

export interface SseMessage {
  event: string
  data: string
}

export class SseParser {
  private buffer = ''
  private eventName = ''
  private dataLines: string[] = []

  /** Feed decoded text; returns every message completed by it. */
  feed(text: string): SseMessage[] {
    this.buffer += text
    const messages: SseMessage[] = []
    for (;;) {
      const match = /\r\n|\n|\r/.exec(this.buffer)
      if (!match) break
      // A lone trailing \r may be the first half of a \r\n split across chunks.
      if (match[0] === '\r' && match.index === this.buffer.length - 1) break
      const line = this.buffer.slice(0, match.index)
      this.buffer = this.buffer.slice(match.index + match[0].length)
      const message = this.processLine(line)
      if (message) messages.push(message)
    }
    return messages
  }

  private processLine(line: string): SseMessage | null {
    if (line === '') {
      const message =
        this.dataLines.length > 0
          ? { event: this.eventName || 'message', data: this.dataLines.join('\n') }
          : null
      this.eventName = ''
      this.dataLines = []
      return message
    }
    if (line.startsWith(':')) return null // comment / keepalive
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') this.eventName = value
    else if (field === 'data') this.dataLines.push(value)
    return null
  }
}

export type RunEvent =
  | { type: 'manifest'; data: ManifestEvent }
  | { type: 'segments'; data: SegmentsEvent }
  | { type: 'job'; data: Job }
  | { type: 'end'; data: EndEvent }

const RUN_EVENT_TYPES = new Set<RunEvent['type']>(['manifest', 'segments', 'job', 'end'])

function toRunEvent(message: SseMessage): RunEvent | null {
  if (!RUN_EVENT_TYPES.has(message.event as RunEvent['type'])) return null
  try {
    return { type: message.event, data: JSON.parse(message.data) } as RunEvent
  } catch {
    return null
  }
}

export type StreamStatus = 'connecting' | 'open' | 'reconnecting' | 'closed' | 'failed'

export interface FollowOptions {
  signal: AbortSignal
  onEvent: (event: RunEvent) => void
  onStatus?: (status: StreamStatus, detail?: string) => void
  /** Delay before reconnect attempt `n` (1-based); exposed for tests. */
  backoffMs?: (attempt: number) => number
}

const defaultBackoff = (attempt: number) => Math.min(1000 * 2 ** (attempt - 1), 10_000)

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms)
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        resolve()
      },
      { once: true },
    )
  })
}

/**
 * Follow a run's events until the server sends `end`, the caller aborts, or
 * the run turns out not to exist. A dropped connection is retried with
 * backoff; the server replays the current manifest and every segment from
 * index 0 on reconnect, and `segments` events carry their `start_index`, so a
 * consumer that splices by index ends up with exactly the server's state.
 */
export async function followRunEvents(runId: string, options: FollowOptions): Promise<void> {
  const { signal, onEvent, onStatus = () => {}, backoffMs = defaultBackoff } = options
  const url = apiUrl(`/api/runs/${encodeURIComponent(runId)}/events`)
  let attempt = 0

  while (!signal.aborted) {
    onStatus(attempt === 0 ? 'connecting' : 'reconnecting')
    let ended = false
    try {
      const response = await fetch(url, {
        headers: { Accept: 'text/event-stream' },
        signal,
        cache: 'no-store',
      })
      if (response.status === 401) {
        noteStatus(401, url)
        onStatus('closed')
        return
      }
      if (response.status === 404) {
        onStatus('failed', 'This run does not exist')
        return
      }
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)

      onStatus('open')
      attempt = 0
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      const parser = new SseParser()
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        for (const message of parser.feed(decoder.decode(value, { stream: true }))) {
          const event = toRunEvent(message)
          if (!event) continue
          onEvent(event)
          if (event.type === 'end') ended = true
        }
      }
    } catch {
      if (signal.aborted) return
    }
    if (ended || signal.aborted) {
      onStatus('closed')
      return
    }
    attempt += 1
    await sleep(backoffMs(attempt), signal)
  }
}

/**
 * Follow the microphone level of your live session until it ends or the
 * caller aborts. A dropped connection is retried a few times; levels are
 * momentary, so nothing is replayed.
 */
export async function followMicLevel(options: {
  signal: AbortSignal
  onLevel: (level: number) => void
}): Promise<void> {
  const { signal, onLevel } = options
  const url = apiUrl('/api/live/level')
  for (let attempt = 1; attempt <= 5 && !signal.aborted; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: { Accept: 'text/event-stream' },
        signal,
        cache: 'no-store',
      })
      // No session (yet, or any more): nothing to follow.
      if (response.status === 404 || response.status === 401) return
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      const parser = new SseParser()
      for (;;) {
        const { value, done } = await reader.read()
        if (done) return // the session ended
        for (const message of parser.feed(decoder.decode(value, { stream: true }))) {
          if (message.event !== 'level') continue
          try {
            const { level } = JSON.parse(message.data) as { level: number }
            onLevel(level)
          } catch {
            // A malformed frame is skipped; the next one is a moment away.
          }
        }
      }
    } catch {
      if (signal.aborted) return
    }
    await sleep(defaultBackoff(attempt), signal)
  }
}
