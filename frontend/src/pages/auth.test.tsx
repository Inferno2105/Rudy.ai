import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { getToken } from '../auth/token'
import { TOKEN } from '../test/fixtures'
import { renderApp } from '../test/render'
import { API, server } from '../test/server'

describe('token gate', () => {
  it('asks for the token before showing anything', async () => {
    renderApp('/', { signedIn: false })
    expect(await screen.findByLabelText('API token')).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
    expect(await screen.findByText(/Server online · v0\.1\.0/)).toBeInTheDocument()
  })

  it('rejects a wrong token with the reason', async () => {
    const { user } = renderApp('/', { signedIn: false })
    await user.type(await screen.findByLabelText('API token'), 'wrong-token')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(
      await screen.findByText(/That token was not accepted by the server./),
    ).toBeInTheDocument()
    expect(getToken()).toBeNull()
  })

  it('opens the app with the right token, held for the session only by default', async () => {
    const { user } = renderApp('/', { signedIn: false })
    await user.type(await screen.findByLabelText('API token'), TOKEN)
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('heading', { name: 'Meetings' })).toBeInTheDocument()
    expect(window.sessionStorage.length).toBe(1)
    expect(window.localStorage.length).toBe(0)
  })

  it('remembers the token on the device only when asked', async () => {
    const { user } = renderApp('/', { signedIn: false })
    await user.type(await screen.findByLabelText('API token'), TOKEN)
    await user.click(screen.getByRole('switch', { name: 'Remember on this device' }))
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await screen.findByRole('heading', { name: 'Meetings' })
    expect(window.localStorage.length).toBe(1)
    expect(window.sessionStorage.length).toBe(0)
  })

  it('returns to the token screen, explaining why, when the server starts rejecting it', async () => {
    server.use(
      http.get(API('/api/runs'), () => HttpResponse.json({ detail: 'nope' }, { status: 401 })),
    )
    renderApp('/')
    expect(await screen.findByText(/rejected the saved token/)).toBeInTheDocument()
    expect(getToken()).toBeNull()
  })

  it('signs out from the sidebar', async () => {
    const { user } = renderApp('/')
    await screen.findByRole('heading', { name: 'Meetings' })
    await user.click(screen.getAllByRole('button', { name: 'Sign out' })[0]!)
    expect(await screen.findByLabelText('API token')).toBeInTheDocument()
    expect(screen.queryByText(/rejected/)).not.toBeInTheDocument()
  })
})
