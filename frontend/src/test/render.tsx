import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'

import { setToken } from '../auth/token'
import { TokenGate } from '../auth/TokenGate'
import { ToastProvider } from '../components/ui/toast'
import { routes } from '../routes'
import { TOKEN } from './fixtures'

/**
 * Render the real app (routes, token gate, providers) at `path`, against the
 * MSW-mocked API. `signedIn` stores the fixture token first.
 */
export function renderApp(path = '/', { signedIn = true } = {}) {
  if (signedIn) setToken(TOKEN, false)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const user = userEvent.setup()
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <TokenGate>
          <RouterProvider router={router} />
        </TokenGate>
      </ToastProvider>
    </QueryClientProvider>,
  )
  return { ...utils, user, router, queryClient }
}
