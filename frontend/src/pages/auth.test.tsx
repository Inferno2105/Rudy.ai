import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import * as f from '../test/fixtures'
import { renderApp } from '../test/render'
import { API, server } from '../test/server'

const signedOut = (setupRequired = false, signupAllowed = true) =>
  http.get(API('/api/auth/status'), () =>
    HttpResponse.json({ setup_required: setupRequired, user: null, signup_allowed: signupAllowed }),
  )

describe('landing page', () => {
  it('is public and invites the visitor to get started', async () => {
    server.use(signedOut())
    renderApp('/')
    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Every voice in your meeting, understood.',
      }),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /Get started/ })[0]).toHaveAttribute(
      'href',
      '/login',
    )
    expect(screen.getByRole('heading', { name: 'From sound to decisions' })).toBeInTheDocument()
  })

  it('offers the meetings instead when already signed in', async () => {
    renderApp('/')
    const links = await screen.findAllByRole('link', { name: /Open your meetings/ })
    expect(links[0]).toHaveAttribute('href', '/meetings')
  })
})

describe('signing in', () => {
  it('sends a signed-out visitor to the sign-in page and back afterwards', async () => {
    let signedIn = false
    server.use(
      http.get(API('/api/auth/status'), () =>
        HttpResponse.json({ setup_required: false, user: signedIn ? f.signedInUser : null }),
      ),
      http.post(API('/api/auth/login'), async ({ request }) => {
        const body = (await request.json()) as { username: string; password: string }
        if (body.password !== 'right-password') {
          return HttpResponse.json({ detail: 'Incorrect username or password.' }, { status: 401 })
        }
        signedIn = true
        return HttpResponse.json(f.signedInUser)
      }),
    )
    const { user, router } = renderApp('/evaluation')
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')

    await user.type(screen.getByLabelText('Username'), 'rushi')
    await user.type(screen.getByLabelText('Password'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Incorrect username or password.')).toBeInTheDocument()

    await user.clear(screen.getByLabelText('Password'))
    await user.type(screen.getByLabelText('Password'), 'right-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('heading', { name: 'Evaluation' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/evaluation')
  })

  it('creates the first account when the server has none', async () => {
    let created: unknown = null
    server.use(
      http.get(API('/api/auth/status'), () =>
        HttpResponse.json(
          created
            ? { setup_required: false, user: f.signedInUser }
            : { setup_required: true, user: null },
        ),
      ),
      http.post(API('/api/auth/setup'), async ({ request }) => {
        created = await request.json()
        return HttpResponse.json(f.signedInUser, { status: 201 })
      }),
    )
    const { user } = renderApp('/login')
    expect(await screen.findByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Username'), 'rushi')
    await user.type(screen.getByLabelText('Password'), 'a-good-password')
    await user.type(screen.getByLabelText('Confirm password'), 'a-different-one')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('The two passwords do not match.')).toBeInTheDocument()
    expect(created).toBeNull()

    await user.clear(screen.getByLabelText('Confirm password'))
    await user.type(screen.getByLabelText('Confirm password'), 'a-good-password')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByRole('heading', { name: 'Meetings' })).toBeInTheDocument()
    expect(created).toEqual({ username: 'rushi', password: 'a-good-password' })
  })

  it('returns to sign-in when the session expires mid-use', async () => {
    let expired = false
    server.use(
      http.get(API('/api/auth/status'), () =>
        HttpResponse.json({ setup_required: false, user: expired ? null : f.signedInUser }),
      ),
      http.get(API('/api/runs'), () => {
        if (!expired) return HttpResponse.json(f.runSummaries)
        return HttpResponse.json({ detail: 'Sign in to continue.' }, { status: 401 })
      }),
    )
    const { user, router } = renderApp('/meetings')
    await screen.findByRole('list', { name: '3 meetings' })
    expired = true
    await user.selectOptions(screen.getByLabelText('Status'), 'partial')
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(router.state.location.search).toContain('next=%2Fmeetings')
  })

  it('signs out from the sidebar', async () => {
    let signedIn = true
    server.use(
      http.get(API('/api/auth/status'), () =>
        HttpResponse.json({ setup_required: false, user: signedIn ? f.signedInUser : null }),
      ),
      http.post(API('/api/auth/logout'), () => {
        signedIn = false
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { user, router } = renderApp('/meetings')
    expect(await screen.findByText('rushi')).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Sign out' })[0]!)
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
  })
})

describe('creating another account', () => {
  it('links from sign-in to sign-up and signs the new account in', async () => {
    let created: unknown = null
    const newcomer = { username: 'priya', created_at: '2026-10-11T12:00:00+00:00' }
    server.use(
      http.get(API('/api/auth/status'), () =>
        HttpResponse.json({
          setup_required: false,
          user: created ? newcomer : null,
          signup_allowed: true,
        }),
      ),
      http.post(API('/api/auth/register'), async ({ request }) => {
        created = await request.json()
        return HttpResponse.json(newcomer, { status: 201 })
      }),
      http.get(API('/api/runs'), () => HttpResponse.json([])),
    )
    const { user, router } = renderApp('/login')
    await user.click(await screen.findByRole('link', { name: 'Create an account' }))
    expect(await screen.findByRole('heading', { name: 'Create an account' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/signup')
    expect(screen.getByText(/no other account can see yours/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('Username'), 'priya')
    await user.type(screen.getByLabelText('Password'), 'a-good-password')
    await user.type(screen.getByLabelText('Confirm password'), 'a-good-password')
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByRole('heading', { name: 'Meetings' })).toBeInTheDocument()
    expect(created).toEqual({ username: 'priya', password: 'a-good-password' })
  })

  it('shows the server refusing a taken username', async () => {
    server.use(
      signedOut(),
      http.post(API('/api/auth/register'), () =>
        HttpResponse.json({ detail: "A user named 'rushi' already exists." }, { status: 422 }),
      ),
    )
    const { user } = renderApp('/signup')
    await user.type(await screen.findByLabelText('Username'), 'rushi')
    await user.type(screen.getByLabelText('Password'), 'a-good-password')
    await user.type(screen.getByLabelText('Confirm password'), 'a-good-password')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText("A user named 'rushi' already exists.")).toBeInTheDocument()
  })

  it('explains when sign-up is turned off, and offers no form', async () => {
    server.use(signedOut(false, false))
    renderApp('/signup')
    expect(await screen.findByText('Sign-up is turned off on this server')).toBeInTheDocument()
    expect(screen.queryByLabelText('Username')).not.toBeInTheDocument()
  })

  it('does not link to sign-up when it is turned off', async () => {
    server.use(signedOut(false, false))
    renderApp('/login')
    await screen.findByRole('heading', { name: 'Welcome back' })
    expect(screen.queryByRole('link', { name: 'Create an account' })).not.toBeInTheDocument()
  })
})

describe('switching accounts', () => {
  it("never shows the previous account's meetings to the next one", async () => {
    let who = f.signedInUser
    const other = { username: 'priya', created_at: '2026-10-11T12:00:00+00:00' }
    server.use(
      http.get(API('/api/auth/status'), () =>
        HttpResponse.json({ setup_required: false, user: who, signup_allowed: true }),
      ),
      http.get(API('/api/runs'), () =>
        HttpResponse.json(who === f.signedInUser ? f.runSummaries : []),
      ),
    )
    const { queryClient } = renderApp('/meetings')
    await screen.findByRole('list', { name: '3 meetings' })

    // Another tab signs this browser in as someone else.
    who = other
    await queryClient.invalidateQueries({ queryKey: ['auth'] })

    expect(await screen.findByText('priya')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: '3 meetings' })).not.toBeInTheDocument()
    expect(
      queryClient.getQueriesData({ queryKey: ['runs'] }).map(([, data]) => data),
    ).not.toContain(f.runSummaries)
  })
})
