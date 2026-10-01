import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { getToken, setToken } from '../auth/token'
import { TOKEN, RUN_ID } from '../test/fixtures'
import { API, server, sseResponse } from '../test/server'
import { followRunEvents, SseParser, type RunEvent, type StreamStatus } from './sse'
import { initialRunEvents, runEventsReducer } from './useRunEvents'

describe('SseParser', () => {
  it('dispatches an event on a blank line', () => {
    const parser = new SseParser()
    expect(parser.feed('event: job\ndata: {"a":1}\n\n')).toEqual([
      { event: 'job', data: '{"a":1}' },
    ])
  })

  it('joins multi-line data with newlines', () => {
    const parser = new SseParser()
    expect(parser.feed('data: one\ndata: two\n\n')).toEqual([
      { event: 'message', data: 'one\ntwo' },
    ])
  })

  it('reassembles an event split across arbitrary chunk boundaries', () => {
    const parser = new SseParser()
    const text = 'event: manifest\ndata: {"status":"partial"}\n\n'
    const messages = [...text].flatMap((char) => parser.feed(char))
    expect(messages).toEqual([{ event: 'manifest', data: '{"status":"partial"}' }])
  })

  it('treats a CRLF split between chunks as one line ending', () => {
    const parser = new SseParser()
    expect(parser.feed('data: x\r')).toEqual([])
    expect(parser.feed('\n\r\n')).toEqual([{ event: 'message', data: 'x' }])
  })

  it('accepts bare CR line endings', () => {
    const parser = new SseParser()
    expect(parser.feed('event: end\rdata: {}\r\r ')).toEqual([{ event: 'end', data: '{}' }])
  })

  it('ignores comments, which the server sends as keepalives', () => {
    const parser = new SseParser()
    expect(parser.feed(': keepalive\n\n')).toEqual([])
    expect(parser.feed(': keepalive\nevent: end\ndata: {}\n\n')).toEqual([
      { event: 'end', data: '{}' },
    ])
  })

  it('strips exactly one leading space from a value', () => {
    const parser = new SseParser()
    expect(parser.feed('data:  two spaces\n\n')).toEqual([
      { event: 'message', data: ' two spaces' },
    ])
  })

  it('does not dispatch an event with no data', () => {
    const parser = new SseParser()
    expect(parser.feed('event: job\n\n')).toEqual([])
  })
})

describe('followRunEvents', () => {
  const eventsUrl = API(`/api/runs/${RUN_ID}/events`)

  async function follow() {
    const events: RunEvent[] = []
    const statuses: StreamStatus[] = []
    const controller = new AbortController()
    await followRunEvents(RUN_ID, {
      signal: controller.signal,
      onEvent: (event) => events.push(event),
      onStatus: (status) => statuses.push(status),
      backoffMs: () => 1,
    })
    return { events, statuses }
  }

  it('sends the token in a header and stops after `end`', async () => {
    setToken(TOKEN, false)
    let authorization: string | null = null
    server.use(
      http.get(eventsUrl, ({ request }) => {
        authorization = request.headers.get('Authorization')
        return sseResponse([
          ['manifest', { status: 'partial', stages: [], extra: {} }],
          ['end', { run_id: RUN_ID }],
        ])
      }),
    )
    const { events, statuses } = await follow()
    expect(authorization).toBe(`Bearer ${TOKEN}`)
    expect(events.map((e) => e.type)).toEqual(['manifest', 'end'])
    expect(statuses.at(-1)).toBe('closed')
  })

  it('reconnects when the stream drops before `end`', async () => {
    setToken(TOKEN, false)
    let attempts = 0
    server.use(
      http.get(eventsUrl, () => {
        attempts += 1
        return attempts === 1
          ? sseResponse([['manifest', { status: 'partial', stages: [], extra: {} }]])
          : sseResponse([['end', { run_id: RUN_ID }]])
      }),
    )
    const { events, statuses } = await follow()
    expect(attempts).toBe(2)
    expect(statuses).toContain('reconnecting')
    expect(events.at(-1)?.type).toBe('end')
  })

  it('signs out on 401 instead of retrying forever', async () => {
    setToken(TOKEN, false)
    server.use(http.get(eventsUrl, () => HttpResponse.json({ detail: 'no' }, { status: 401 })))
    const { statuses } = await follow()
    expect(statuses.at(-1)).toBe('closed')
    expect(getToken()).toBeNull()
  })

  it('gives up on a run that does not exist', async () => {
    setToken(TOKEN, false)
    server.use(http.get(eventsUrl, () => HttpResponse.json({ detail: 'nope' }, { status: 404 })))
    const { statuses } = await follow()
    expect(statuses.at(-1)).toBe('failed')
  })
})

describe('runEventsReducer', () => {
  const segment = (text: string) => ({ start: 0, end: 1, text })

  it('appends segments at their start index', () => {
    let state = runEventsReducer(initialRunEvents, {
      kind: 'event',
      event: { type: 'segments', data: { start_index: 0, segments: [segment('a')] } },
    })
    state = runEventsReducer(state, {
      kind: 'event',
      event: { type: 'segments', data: { start_index: 1, segments: [segment('b')] } },
    })
    expect(state.segments.map((s) => s.text)).toEqual(['a', 'b'])
  })

  it('does not duplicate segments when a reconnect replays from zero', () => {
    let state = runEventsReducer(initialRunEvents, {
      kind: 'event',
      event: { type: 'segments', data: { start_index: 0, segments: [segment('a'), segment('b')] } },
    })
    state = runEventsReducer(state, {
      kind: 'event',
      event: {
        type: 'segments',
        data: { start_index: 0, segments: [segment('a'), segment('b'), segment('c')] },
      },
    })
    expect(state.segments.map((s) => s.text)).toEqual(['a', 'b', 'c'])
  })
})
