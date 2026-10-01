import { QueryClient } from '@tanstack/react-query'
import type { RouteObject } from 'react-router'

import { shouldRetry } from './api/queries'
import { AppShell } from './components/AppShell'
import { MeetingsPage } from './pages/MeetingsPage'

// Every page but the landing one is loaded on first visit, so opening the app
// does not download charting code it may never use.
export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { index: true, element: <MeetingsPage /> },
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
        lazy: async () => ({ Component: (await import('./pages/EvaluationPage')).EvaluationPage }),
      },
      {
        path: '*',
        lazy: async () => ({ Component: (await import('./pages/NotFoundPage')).NotFoundPage }),
      },
    ],
  },
]

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, staleTime: 5_000, refetchOnWindowFocus: true },
      mutations: { retry: false },
    },
  })
}
