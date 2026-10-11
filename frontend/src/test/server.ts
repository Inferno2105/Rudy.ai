import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import * as f from './fixtures'

export const API = (path: string) => `${window.location.origin}${path}`

const notFound = (detail: string) => HttpResponse.json({ detail }, { status: 404 })

/** A happy-path API: one completed-ish batch run with every artifact but the LLM ones. */
export const defaultHandlers = [
  http.get(API('/api/health'), () => HttpResponse.json(f.health)),
  http.get(API('/api/jobs/current'), () => HttpResponse.json(null)),
  http.get(API('/api/runs'), () => HttpResponse.json(f.runSummaries)),
  http.get(API('/api/runs/:runId'), ({ params }) =>
    params.runId === f.RUN_ID ? HttpResponse.json(f.runDetail()) : notFound('Run not found'),
  ),
  http.get(API('/api/runs/:runId/transcript'), () => HttpResponse.json(f.transcript)),
  http.get(API('/api/runs/:runId/summary'), () => notFound('Run has no summary artifact (yet)')),
  http.get(API('/api/runs/:runId/action-items'), () =>
    notFound('Run has no action_items artifact (yet)'),
  ),
  http.get(API('/api/runs/:runId/speakers'), () => HttpResponse.json(f.speakers)),
  http.get(API('/api/runs/:runId/metadata'), () => HttpResponse.json(f.metadata)),
  http.get(API('/api/runs/:runId/artifacts/tagged'), () => HttpResponse.json(f.taggedSegments)),
  http.get(API('/api/audio'), () =>
    HttpResponse.json([{ name: 'test_hindi.wav', size_bytes: 1097694, duration_sec: 34.3 }]),
  ),
  http.get(API('/api/devices'), () =>
    HttpResponse.json([
      {
        index: 1,
        name: 'Microphone Array',
        channels: 2,
        default_samplerate: 48000,
        is_default: true,
      },
      { index: 3, name: 'Headset', channels: 1, default_samplerate: 16000, is_default: false },
    ]),
  ),
  http.get(API('/api/eval/report'), () =>
    notFound('No evaluation report yet; run `meeting-assistant eval`'),
  ),
]

export const server = setupServer(...defaultHandlers)

/** An SSE response that emits `events` (as `[name, payload]`) then closes. */
export function sseResponse(
  events: [string, unknown][],
  { delayMs = 0 } = {},
): HttpResponse<ReadableStream> {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    async start(controller) {
      for (const [name, payload] of events) {
        if (delayMs) await new Promise((resolve) => setTimeout(resolve, delayMs))
        controller.enqueue(encoder.encode(`event: ${name}\ndata: ${JSON.stringify(payload)}\n\n`))
      }
      controller.close()
    },
  })
  return new HttpResponse(stream, { headers: { 'Content-Type': 'text/event-stream' } })
}
