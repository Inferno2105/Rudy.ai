import { QueryClient } from '@tanstack/react-query'
import type { RouteObject } from 'react-router'

import { setUnauthorizedHandler } from './api/client'
import { keys, shouldRetry } from './api/queries'
import { AppShell } from './components/AppShell'
import { RequireAuth } from './components/RequireAuth'
import { LandingPage } from './pages/LandingPage'
import { LoginPage } from './pages/LoginPage'
import { MeetingsPage } from './pages/MeetingsPage'

// The landing and sign-in pages are public; everything under the app shell
// needs a signed-in user. App pages other than Meetings load on first visit,
// so opening the app does not download charting code it may never use.
export const routes: RouteObject[] = [
  { path: '/', element: <LandingPage /> },
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: 'meetings', element: <MeetingsPage /> },
          {
            path: 'new',
            lazy: async () => ({ Component: (await import('./pages/NewRunPage')).NewRunPage }),
          },
          {
            path: 'live',
            lazy: async () => ({ Component: (await import('./pages/LivePage')).LivePage }),
          },
          {
            path: 'runs/:runId',
            lazy: async () => ({ Component: (await import('./pages/run/RunPage')).RunPage }),
          },
          {
            path: 'evaluation',
            lazy: async () => ({
              Component: (await import('./pages/EvaluationPage')).EvaluationPage,
            }),
          },
          {
            path: '*',
            lazy: async () => ({ Component: (await import('./pages/NotFoundPage')).NotFoundPage }),
          },
        ],
      },
    ],
  },
]

/** When any request finds the session gone, re-check who is signed in; the
 * route guard then sends the user to the sign-in page. */
export function watchSession(client: QueryClient): QueryClient {
  setUnauthorizedHandler(() => void client.invalidateQueries({ queryKey: keys.auth }))
  return client
}

export function createQueryClient(): QueryClient {
  return watchSession(
    new QueryClient({
      defaultOptions: {
        queries: { retry: shouldRetry, staleTime: 5_000, refetchOnWindowFocus: true },
        mutations: { retry: false },
      },
    }),
  )
}
