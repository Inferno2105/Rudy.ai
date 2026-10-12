import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { TranslationStatus } from '../api/types'
import * as f from '../test/fixtures'
import { renderApp } from '../test/render'
import { API, server } from '../test/server'

const RUN_PATH = `/runs/${f.RUN_ID}`
const TRANSLATION = API('/api/runs/:runId/translations/:target')

const englishSegments = [
  "Hello everyone, let's start the meeting",
  'Let us review the release plan first',
  'The release is on Friday, testing by tomorrow',
  'okay',
].map((text, i) => ({ ...f.hinglishSegments[i]!, text }))

/** A server that translates when asked: missing, then running, then ready. */
function translatingServer() {
  const calls = { posts: 0 }
  let state: TranslationStatus['state'] = 'missing'
  let polls = 0
  server.use(
    http.get(TRANSLATION, ({ params }) => {
      if (state === 'running' && ++polls > 1) state = 'ready'
      const body: TranslationStatus =
        state === 'ready'
          ? {
              target: params.target as 'english',
              state,
              done: 4,
              total: 4,
              model: 'qwen2.5:7b',
              segments_failed: 0,
              segments: englishSegments,
            }
          : state === 'running'
            ? { target: 'english', state, done: 1, total: 4, segments_failed: 0 }
            : { target: 'english', state, segments_failed: 0 }
      return HttpResponse.json(body)
    }),
    http.post(TRANSLATION, () => {
      calls.posts += 1
      state = 'running'
      return HttpResponse.json(
        { target: 'english', state, done: 0, total: 4, segments_failed: 0 },
        { status: 202 },
      )
    }),
  )
  return calls
}

describe('transcript translations', () => {
  it('translates the transcript into English when that view is chosen', async () => {
    const calls = translatingServer()
    const { user, router } = renderApp(RUN_PATH)
    await screen.findByRole('list', { name: 'Transcript' })

    await user.click(screen.getByRole('radio', { name: 'English' }))
    expect(router.state.location.search).toContain('script=english')
    expect(await screen.findByText('Translating into English…')).toBeInTheDocument()

    expect(
      await screen.findByText("Hello everyone, let's start the meeting", {}, { timeout: 5000 }),
    ).toBeInTheDocument()
    expect(screen.getByText(/machine translation into English by/)).toBeInTheDocument()
    expect(calls.posts).toBe(1)
  })

  it('opens a translated view from a link', async () => {
    server.use(
      http.get(TRANSLATION, () =>
        HttpResponse.json({
          target: 'english',
          state: 'ready',
          model: 'qwen2.5:7b',
          segments_failed: 0,
          segments: englishSegments,
        } satisfies TranslationStatus),
      ),
    )
    renderApp(`${RUN_PATH}?script=english`)
    expect(await screen.findByText("Hello everyone, let's start the meeting")).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'English' })).toBeChecked()
  })

  it('says why a translation failed and offers to try again', async () => {
    let posts = 0
    server.use(
      http.get(TRANSLATION, () =>
        HttpResponse.json({
          target: 'hindi',
          state: 'failed',
          error: 'LLMError: Ollama request failed',
          segments_failed: 0,
        } satisfies TranslationStatus),
      ),
      http.post(TRANSLATION, () => {
        posts += 1
        return HttpResponse.json(
          { target: 'hindi', state: 'queued', segments_failed: 0 },
          { status: 202 },
        )
      }),
    )
    const { user } = renderApp(`${RUN_PATH}?script=hindi`)
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText('Could not translate into Hindi')).toBeInTheDocument()
    expect(within(alert).getByText(/Ollama request failed/)).toBeInTheDocument()
    // A failure is not retried behind the reader's back.
    expect(posts).toBe(0)
    await user.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(posts).toBe(1)
  })
})

describe('transcript PDF', () => {
  it('links the PDF of the chosen version', async () => {
    const { user } = renderApp(`${RUN_PATH}?tab=artifacts`)
    const link = await screen.findByRole('link', { name: 'Download PDF' })
    expect(link.getAttribute('href')).toMatch(/\/transcript\.pdf\?version=original$/)

    await user.click(screen.getByRole('radio', { name: 'Romanized' }))
    expect(screen.getByRole('link', { name: 'Download PDF' }).getAttribute('href')).toMatch(
      /version=romanized$/,
    )
  })

  it('asks for a translation before the translated PDF', async () => {
    const calls = translatingServer()
    const { user } = renderApp(`${RUN_PATH}?tab=artifacts`)
    await screen.findByRole('link', { name: 'Download PDF' })

    await user.click(screen.getByRole('radio', { name: 'English' }))
    const translate = await screen.findByRole('button', { name: 'Translate into English' })
    expect(screen.queryByRole('link', { name: 'Download PDF' })).not.toBeInTheDocument()
    // Choosing the version does not start a translation by itself here.
    expect(calls.posts).toBe(0)

    await user.click(translate)
    const link = await screen.findByRole('link', { name: 'Download PDF' }, { timeout: 5000 })
    expect(link.getAttribute('href')).toMatch(/version=english$/)
    expect(calls.posts).toBe(1)
  })

  it('disables the romanized version when there is no romanized transcript', async () => {
    server.use(
      http.get(API('/api/runs/:runId'), () =>
        HttpResponse.json(
          f.runDetail({ artifacts: ['transcript', 'aligned', 'merged', 'tagged'] }),
        ),
      ),
    )
    renderApp(`${RUN_PATH}?tab=artifacts`)
    expect(await screen.findByRole('radio', { name: 'Romanized' })).toBeDisabled()
  })
})
