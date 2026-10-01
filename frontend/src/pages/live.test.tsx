import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import * as f from '../test/fixtures'
import { renderApp } from '../test/render'
import { API, server, sseResponse } from '../test/server'

const LIVE_RUN = '20261001-160000_live_mic'

describe('live page', () => {
  it('preselects the default microphone', async () => {
    renderApp('/live')
    const select = await screen.findByLabelText('Microphone')
    expect(select).toHaveValue('1')
  })

  it('starts, streams segments, stops and links to the finished meeting', async () => {
    let body: unknown = null
    let stopped = false
    const liveJob = f.job({ kind: 'live', run_id: LIVE_RUN })
    server.use(
      http.post(API('/api/live/start'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ job_id: 'job-2', run_id: LIVE_RUN }, { status: 202 })
      }),
      http.post(API('/api/live/stop'), () => {
        stopped = true
        return HttpResponse.json(f.job({ kind: 'live', run_id: LIVE_RUN, state: 'stopping' }), {
          status: 202,
        })
      }),
      http.get(API(`/api/runs/${LIVE_RUN}/events`), () =>
        sseResponse(
          [
            ['job', liveJob],
            [
              'segments',
              {
                start_index: 0,
                segments: [
                  {
                    start: 0,
                    end: 2,
                    speaker: 'SPEAKER_G01',
                    text: 'pehla chunk',
                    language: 'Hindi',
                  },
                ],
              },
            ],
            [
              'segments',
              {
                start_index: 1,
                segments: [
                  {
                    start: 2,
                    end: 4,
                    speaker: 'SPEAKER_G02',
                    text: 'second chunk',
                    language: 'English',
                  },
                ],
              },
            ],
            [
              'manifest',
              {
                status: 'completed',
                stages: [],
                extra: {
                  live_stats: { chunks_recorded: 2, chunks_processed: 2, realtime_factor: 1.455 },
                },
              },
            ],
            ['job', { ...liveJob, state: 'finished' }],
            ['end', { run_id: LIVE_RUN }],
          ],
          { delayMs: 30 },
        ),
      ),
    )

    const { user } = renderApp('/live')
    await user.selectOptions(await screen.findByLabelText('Microphone'), '3')
    await user.type(screen.getByLabelText('Number of speakers'), '2')
    await user.click(screen.getByRole('button', { name: 'Start recording' }))

    const transcript = await screen.findByRole('list', { name: 'Live transcript' })
    expect(await within(transcript).findByText('second chunk')).toBeInTheDocument()
    expect(within(transcript).getByText('pehla chunk')).toBeInTheDocument()
    expect(body).toEqual({ device: 3, num_speakers: 2, use_registry: true })

    expect(await screen.findByText('Session finished')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open meeting/ })).toHaveAttribute(
      'href',
      `/runs/${LIVE_RUN}`,
    )
    expect(screen.getByText('1.455')).toBeInTheDocument()
    expect(stopped).toBe(false) // the session ended on its own in this script
  })

  it('stops a running session', async () => {
    let stopped = false
    const liveJob = f.job({ kind: 'live', run_id: LIVE_RUN })
    server.use(
      http.get(API('/api/jobs/current'), () => HttpResponse.json(liveJob)),
      http.post(API('/api/live/stop'), () => {
        stopped = true
        return HttpResponse.json({ ...liveJob, state: 'stopping' }, { status: 202 })
      }),
      http.get(
        API(`/api/runs/${LIVE_RUN}/events`),
        () =>
          // Stays open (no `end`) like a real recording in progress.
          new HttpResponse(
            new ReadableStream({
              start(controller) {
                controller.enqueue(
                  new TextEncoder().encode(`event: job\ndata: ${JSON.stringify(liveJob)}\n\n`),
                )
              },
            }),
            { headers: { 'Content-Type': 'text/event-stream' } },
          ),
      ),
    )
    const { user } = renderApp('/live')
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
    await user.click(screen.getByRole('button', { name: 'Start recording' }))
    expect(await screen.findByText(/Busy with batch job job-1/)).toBeInTheDocument()
  })
})
