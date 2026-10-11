import { fireEvent, screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import * as f from '../test/fixtures'
import { renderApp } from '../test/render'
import { API, server } from '../test/server'

describe('new run', () => {
  it('starts a run on an existing recording and opens its page', async () => {
    let body: unknown = null
    server.use(
      http.post(API('/api/runs/batch'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ job_id: 'job-9', run_id: f.RUN_ID }, { status: 202 })
      }),
    )
    const { user, router } = renderApp('/new')
    await user.click(await screen.findByRole('radio', { name: /test_hindi\.wav/ }))
    await user.type(screen.getByLabelText('Number of speakers'), '2')
    await user.click(screen.getByRole('button', { name: 'Start processing' }))
    await screen.findByRole('heading', { level: 1, name: 'test_hindi.wav' })
    expect(body).toEqual({ audio: 'test_hindi.wav', num_speakers: 2 })
    expect(router.state.location.pathname).toBe(`/runs/${f.RUN_ID}`)
  })

  it('keeps an invalid speaker count from submitting and focuses the field', async () => {
    let posted = false
    server.use(
      http.post(API('/api/runs/batch'), () => {
        posted = true
        return HttpResponse.json({ job_id: 'j', run_id: f.RUN_ID }, { status: 202 })
      }),
    )
    const { user } = renderApp('/new')
    await user.click(await screen.findByRole('radio', { name: /test_hindi\.wav/ }))
    const field = screen.getByLabelText('Number of speakers')
    await user.type(field, '0')
    expect(screen.getByText('Enter a whole number from 1 to 20.')).toBeInTheDocument()
    // The button stays enabled; submitting explains and focuses instead.
    await user.click(screen.getByRole('button', { name: 'Start processing' }))
    expect(field).toHaveFocus()
    expect(posted).toBe(false)
  })

  it('asks for a recording when none is chosen', async () => {
    const { user } = renderApp('/new')
    await screen.findByRole('radio', { name: /test_hindi\.wav/ })
    await user.click(screen.getByRole('button', { name: 'Start processing' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Choose or upload a recording first.')
    expect(screen.getByText('None selected')).toHaveFocus()
    await user.click(screen.getByRole('radio', { name: /test_hindi\.wav/ }))
    expect(screen.queryByText('Choose or upload a recording first.')).not.toBeInTheDocument()
  })

  it('uploads a recording and selects it', async () => {
    server.use(
      http.post(API('/api/uploads'), () =>
        HttpResponse.json(
          {
            name: 'standup.wav',
            size_bytes: 4,
            duration_sec: 1,
            sha256: 'x',
            already_present: false,
          },
          { status: 201 },
        ),
      ),
    )
    const { user } = renderApp('/new')
    const file = new File(['RIFF'], 'Standup.wav', { type: 'audio/wav' })
    await user.upload(await screen.findByLabelText('Recording file'), file)
    expect(await screen.findByText('Uploaded standup.wav and selected it.')).toBeInTheDocument()
  })

  it('shows the server reason when an upload is refused', async () => {
    server.use(
      http.post(API('/api/uploads'), () =>
        HttpResponse.json(
          { detail: 'A different file named standup.wav already exists' },
          { status: 409 },
        ),
      ),
    )
    const { user } = renderApp('/new')
    const file = new File(['RIFF'], 'standup.wav', { type: 'audio/wav' })
    await user.upload(await screen.findByLabelText('Recording file'), file)
    expect(
      await screen.findByText('A different file named standup.wav already exists'),
    ).toBeInTheDocument()
  })

  it('refuses unsupported file types before uploading', async () => {
    // The accept attribute does not filter drag-and-drop, so the page checks
    // the type itself; dispatch the change directly to bypass the attribute.
    renderApp('/new')
    const file = new File(['x'], 'notes.txt', { type: 'text/plain' })
    fireEvent.change(await screen.findByLabelText('Recording file'), { target: { files: [file] } })
    expect(await screen.findByText(/notes\.txt is not a supported recording/)).toBeInTheDocument()
  })
})

describe('evaluation', () => {
  it('explains how to produce a report when there is none', async () => {
    renderApp('/evaluation')
    expect(await screen.findByText('No evaluation report yet')).toBeInTheDocument()
  })

  it('shows which commit and config each clip was scored with, not only on hover', async () => {
    server.use(http.get(API('/api/eval/report'), () => HttpResponse.json(f.evalReport)))
    renderApp('/evaluation')
    expect(await screen.findByText(/commit abcdef1 · config 108acd72/)).toBeVisible()
  })

  it('shows aggregate metrics exactly as reported and links each clip to its run', async () => {
    server.use(http.get(API('/api/eval/report'), () => HttpResponse.json(f.evalReport)))
    renderApp('/evaluation')
    expect(await screen.findByText('Mean across clips')).toBeInTheDocument()
    expect(screen.getAllByText('0.213').length).toBeGreaterThan(0)
    expect(screen.getAllByText('0.152').length).toBeGreaterThan(0)
    const table = screen.getByRole('table')
    expect(within(table).getByRole('link', { name: f.RUN_ID })).toHaveAttribute(
      'href',
      `/runs/${f.RUN_ID}?tab=provenance`,
    )
    expect(screen.queryByText('These results mix configurations')).not.toBeInTheDocument()
  })

  it('warns when the scored runs span several configurations', async () => {
    server.use(
      http.get(API('/api/eval/report'), () =>
        HttpResponse.json({ ...f.evalReport, config_hashes: ['108acd72e0ed', '3b9ef22c114d'] }),
      ),
    )
    renderApp('/evaluation')
    expect(await screen.findByText('These results mix configurations')).toBeInTheDocument()
  })
})
