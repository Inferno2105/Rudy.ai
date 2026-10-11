import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { renderApp } from '../test/render'
import { API, server } from '../test/server'

describe('meetings list', () => {
  it('lists runs by recording name with status and origin', async () => {
    renderApp('/')
    const list = await screen.findByRole('list', { name: '3 meetings' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(3)
    expect(within(rows[0]!).getByRole('link', { name: 'test_hindi.wav' })).toHaveAttribute(
      'href',
      '/runs/20261001-152823_batch_test_hindi',
    )
    expect(within(rows[1]!).getByText('Partial')).toBeInTheDocument()
    expect(within(rows[2]!).getByRole('link', { name: 'Live session' })).toBeInTheDocument()
  })

  it('filters by search text without a server round trip', async () => {
    const { user } = renderApp('/')
    await screen.findByRole('list', { name: '3 meetings' })
    await user.type(screen.getByLabelText('Search meetings'), 'standup')
    const rows = within(screen.getByRole('list', { name: '1 meeting' })).getAllByRole('listitem')
    expect(rows).toHaveLength(1)
    expect(within(rows[0]!).getByText('standup.wav')).toBeInTheDocument()
  })

  it('passes status and mode filters to the server and keeps them in the URL', async () => {
    const seen: string[] = []
    server.use(
      http.get(API('/api/runs'), ({ request }) => {
        seen.push(new URL(request.url).search)
        return HttpResponse.json([])
      }),
    )
    const { user, router } = renderApp('/')
    await user.selectOptions(await screen.findByLabelText('Status'), 'partial')
    await screen.findByText('No meetings match these filters')
    expect(seen.at(-1)).toContain('status=partial')
    expect(router.state.location.search).toBe('?status=partial')
  })

  it('shows a first-run empty state when there are no runs at all', async () => {
    server.use(http.get(API('/api/runs'), () => HttpResponse.json([])))
    renderApp('/')
    expect(await screen.findByText('No meetings yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Process a recording' })).toHaveAttribute(
      'href',
      '/new',
    )
  })

  it('shows the server error and recovers on retry', async () => {
    let fail = true
    server.use(
      http.get(API('/api/runs'), () =>
        fail
          ? HttpResponse.json({ detail: 'database is locked' }, { status: 500 })
          : HttpResponse.json([]),
      ),
    )
    const { user } = renderApp('/')
    expect(await screen.findByText('database is locked')).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('No meetings yet')).toBeInTheDocument()
  })

  it('rebuilds the index and reports the count', async () => {
    server.use(
      http.post(API('/api/index/rebuild'), () => HttpResponse.json({ indexed: 3, total: 3 })),
    )
    const { user } = renderApp('/')
    await screen.findByRole('list', { name: '3 meetings' })
    await user.click(screen.getByRole('button', { name: /Rebuild index/ }))
    expect(await screen.findByText('Indexed 3 of 3 runs from disk.')).toBeInTheDocument()
  })
})

describe('meetings overview', () => {
  it('shows speakers, language mix and summary stats from the run list', async () => {
    renderApp('/')
    const list = await screen.findByRole('list', { name: '3 meetings' })
    const first = within(list).getAllByRole('listitem')[0]!
    expect(within(first).getByText('2 speakers')).toBeInTheDocument()
    expect(within(first).getByText(/Language mix: Hindi 60%, English 40%/)).toBeInTheDocument()
    expect(screen.getByText('Minutes of speech')).toBeInTheDocument()
  })
})
