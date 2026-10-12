import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import * as f from '../test/fixtures'
import { renderApp } from '../test/render'
import { API, server, sseResponse } from '../test/server'

const LIVE_RUN = '20261001-160000_live_mic'
const STEPS = ['speech', 'speakers', 'tracking', 'microphone']

/** An event stream the test drives: each `send` arrives as the server would send it. */
function controlledStream() {
  const encoder = new TextEncoder()
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c
    },
  })
  return {
    response: () => new HttpResponse(stream, { headers: { 'Content-Type': 'text/event-stream' } }),
    send(event: string, data: unknown) {
      controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`))
    },
    close() {
      controller.close()
    },
  }
}

function phase(livePhase: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return {
    status: 'partial',
    stages: [],
    extra: { live_phase: { steps: STEPS, ...livePhase }, ...extra },
  }
}

describe('live page', () => {
  it('preselects the default microphone', async () => {
    renderApp('/live')
    const select = await screen.findByLabelText('Microphone')
    expect(select).toHaveValue('1')
  })

  it('gets ready, waits for the go, then records, streams and links to the meeting', async () => {
    let body: unknown = null
    let recordCalls = 0
    const events = controlledStream()
    const liveJob = f.job({ kind: 'live', run_id: LIVE_RUN })
    server.use(
      http.post(API('/api/live/start'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ job_id: 'job-2', run_id: LIVE_RUN }, { status: 202 })
      }),
      http.post(API('/api/live/record'), () => {
        recordCalls += 1
        return HttpResponse.json(liveJob, { status: 202 })
      }),
      http.get(API(`/api/runs/${LIVE_RUN}/events`), () => events.response()),
      http.get(API('/api/live/level'), () =>
        sseResponse(
          [0.1, 0.6, 0.5, 0.4, 0.55, 0.3, 0.45, 0.5].map((level) => ['level', { level }]),
        ),
      ),
    )

    const { user } = renderApp('/live')
    await user.selectOptions(await screen.findByLabelText('Microphone'), '3')
    await user.type(screen.getByLabelText('Number of speakers'), '2')
    await user.click(screen.getByRole('button', { name: 'Get ready' }))
    expect(body).toEqual({ device: 3, num_speakers: 2, use_registry: true })

    // Getting ready: nothing to start yet, each step reported as it loads.
    events.send('job', liveJob)
    events.send('manifest', phase({ phase: 'loading', step: 'speakers' }))
    expect(await screen.findByText('Getting ready…')).toBeInTheDocument()
    const steps = screen.getByRole('list', { name: 'Preparation' })
    expect(within(steps).getAllByRole('listitem')).toHaveLength(4)
    expect(within(steps).getByText('Speaker separation model').parentElement).toHaveTextContent(
      'loading',
    )
    expect(screen.queryByRole('button', { name: 'Start recording' })).not.toBeInTheDocument()

    // All systems go: the microphone is open and its level shows.
    events.send('manifest', phase({ phase: 'ready', step: null }))
    expect(await screen.findByText('All systems go')).toBeInTheDocument()
    expect(await screen.findByRole('meter', { name: 'Microphone level' })).toBeInTheDocument()
    expect(await screen.findByText('The microphone is picking you up.')).toBeInTheDocument()
    expect(recordCalls).toBe(0)

    await user.click(screen.getByRole('button', { name: 'Start recording' }))
    expect(recordCalls).toBe(1)

    events.send(
      'manifest',
      phase({ phase: 'recording', step: null, recording_started_at: '2026-10-01T16:00:05.000' }),
    )
    events.send('segments', {
      start_index: 0,
      segments: [
        { start: 0, end: 2, speaker: 'SPEAKER_G01', text: 'pehla chunk', language: 'Hindi' },
      ],
    })
    events.send('segments', {
      start_index: 1,
      segments: [
        { start: 2, end: 4, speaker: 'SPEAKER_G02', text: 'second chunk', language: 'English' },
      ],
    })

    // The scrolling area is a named, keyboard-focusable region.
    const region = await screen.findByRole('region', { name: 'Live transcript, scrollable' })
    expect(region).toHaveAttribute('tabindex', '0')
    const transcript = await screen.findByRole('list', { name: 'Live transcript' })
    expect(await within(transcript).findByText('second chunk')).toBeInTheDocument()
    expect(within(transcript).getByText('pehla chunk')).toBeInTheDocument()

    events.send('manifest', {
      ...phase({ phase: 'finishing', recording_started_at: '2026-10-01T16:00:05.000' }),
      status: 'completed',
      extra: {
        live_phase: { phase: 'finishing', steps: STEPS },
        live_stats: { chunks_recorded: 2, chunks_processed: 2, realtime_factor: 1.455 },
      },
    })
    events.send('job', { ...liveJob, state: 'finished' })
    events.send('end', { run_id: LIVE_RUN })
    events.close()

    expect(await screen.findByText('Session finished')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open meeting/ })).toHaveAttribute(
      'href',
      `/runs/${LIVE_RUN}`,
    )
    expect(screen.getByText('1.455')).toBeInTheDocument()
  })

  it('cancels while getting ready and returns to the start form', async () => {
    let stopped = false
    const events = controlledStream()
    const liveJob = f.job({ kind: 'live', run_id: LIVE_RUN })
    server.use(
      http.post(API('/api/live/start'), () =>
        HttpResponse.json({ job_id: 'job-2', run_id: LIVE_RUN }, { status: 202 }),
      ),
      http.post(API('/api/live/stop'), () => {
        stopped = true
        return HttpResponse.json({ ...liveJob, state: 'stopping' }, { status: 202 })
      }),
      http.get(API(`/api/runs/${LIVE_RUN}/events`), () => events.response()),
    )
    const { user } = renderApp('/live')
    await screen.findByLabelText('Microphone')
    await user.click(screen.getByRole('button', { name: 'Get ready' }))
    events.send('job', liveJob)
    events.send('manifest', phase({ phase: 'loading', step: 'speech' }))

    await user.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(stopped).toBe(true)
    expect(await screen.findByText('Cancelling…')).toBeInTheDocument()

    events.send('job', { ...liveJob, state: 'finished' })
    events.send('end', { run_id: LIVE_RUN })
    events.close()
    expect(await screen.findByRole('button', { name: 'Get ready' })).toBeInTheDocument()
  })

  it('says so when a session fails before recording', async () => {
    const liveJob = f.job({ kind: 'live', run_id: LIVE_RUN })
    server.use(
      http.post(API('/api/live/start'), () =>
        HttpResponse.json({ job_id: 'job-2', run_id: LIVE_RUN }, { status: 202 }),
      ),
      http.get(API(`/api/runs/${LIVE_RUN}/events`), () =>
        sseResponse([
          ['manifest', phase({ phase: 'loading', step: 'speech' })],
          ['job', { ...liveJob, state: 'failed', error: 'ConfigError: HF_TOKEN is not set' }],
          ['end', { run_id: LIVE_RUN }],
        ]),
      ),
    )
    const { user } = renderApp('/live')
    await screen.findByLabelText('Microphone')
    await user.click(screen.getByRole('button', { name: 'Get ready' }))
    expect(
      await screen.findByText('The session ended before recording started'),
    ).toBeInTheDocument()
    expect(screen.getByText(/HF_TOKEN is not set/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New session' })).toBeInTheDocument()
  })

  it('stops a running session', async () => {
    let stopped = false
    const liveJob = f.job({ kind: 'live', run_id: LIVE_RUN })
    const events = controlledStream()
    server.use(
      http.get(API('/api/jobs/current'), () => HttpResponse.json(liveJob)),
      http.post(API('/api/live/stop'), () => {
        stopped = true
        return HttpResponse.json({ ...liveJob, state: 'stopping' }, { status: 202 })
      }),
      // Stays open (no `end`) like a real recording in progress.
      http.get(API(`/api/runs/${LIVE_RUN}/events`), () => events.response()),
    )
    const { user } = renderApp('/live')
    events.send('job', liveJob)
    events.send(
      'manifest',
      phase({ phase: 'recording', recording_started_at: '2026-10-01T16:00:05.000' }),
    )
    // Attaches to the session already running on the server.
    const stop = await screen.findByRole('button', { name: 'Stop' })
    const status = (await screen.findByText('Status')).parentElement!
    expect(await within(status).findByText('Running')).toBeInTheDocument()
    await user.click(stop)
    expect(stopped).toBe(true)
  })

  it('explains why recording cannot start while the server is busy', async () => {
    server.use(
      http.post(API('/api/live/start'), () =>
        HttpResponse.json(
          { detail: 'Busy with batch job job-1 (run 20261001-152823_batch_test_hindi)' },
          { status: 409 },
        ),
      ),
    )
    const { user } = renderApp('/live')
    await screen.findByLabelText('Microphone')
    await user.click(screen.getByRole('button', { name: 'Get ready' }))
    expect(await screen.findByText(/Busy with batch job job-1/)).toBeInTheDocument()
  })
})
