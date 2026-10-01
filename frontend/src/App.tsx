import { QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router'

import { TokenGate } from './auth/TokenGate'
import { ToastProvider } from './components/ui/toast'
import { createQueryClient, routes } from './routes'

export function App() {
  const [queryClient] = useState(createQueryClient)
  const [router] = useState(() => createBrowserRouter(routes))
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <TokenGate>
          <RouterProvider router={router} />
        </TokenGate>
      </ToastProvider>
    </QueryClientProvider>
  )
}
