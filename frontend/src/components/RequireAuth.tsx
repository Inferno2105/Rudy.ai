import { Navigate, Outlet, useLocation } from 'react-router'

import { useAuthStatus } from '../api/queries'
import { BrandMark } from './visuals'

/**
 * Renders the app only for a signed-in user; anyone else is sent to the
 * sign-in page, which brings them back here afterwards.
 */
export function RequireAuth() {
  const status = useAuthStatus()
  const location = useLocation()

  if (status.isPending) {
    return (
      <output className="grid min-h-dvh place-items-center">
        <span className="flex flex-col items-center gap-3">
          <BrandMark className="size-12" />
          <span className="text-muted text-sm">Opening your workspace…</span>
        </span>
      </output>
    )
  }
  if (!status.data?.user) {
    const next = `${location.pathname}${location.search}`
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />
  }
  return <Outlet />
}
