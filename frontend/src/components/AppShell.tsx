import { BarChart3, ListMusic, Menu, Mic, Monitor, Moon, Sun, Upload, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'

import { useCurrentJob, useHealth } from '../api/queries'
import { isJobActive } from '../api/types'
import { useTheme, type ThemePreference } from '../lib/theme'
import { cn } from '../lib/utils'
import { JobStateBadge } from './status'
import { Button } from './ui/button'

const NAV = [
  { to: '/', label: 'Meetings', icon: ListMusic, end: true },
  { to: '/new', label: 'New run', icon: Upload, end: false },
  { to: '/live', label: 'Live', icon: Mic, end: false },
  { to: '/evaluation', label: 'Evaluation', icon: BarChart3, end: false },
]

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main">
      <ul className="space-y-0.5">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  'flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-accent-soft text-accent'
                    : 'text-muted hover:bg-subtle hover:text-fg',
                )
              }
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}

function HealthIndicator() {
  const health = useHealth()
  const state = health.isPending
    ? { dot: 'bg-faint', text: 'Connecting' }
    : health.isError
      ? { dot: 'bg-danger', text: 'Server unreachable' }
      : health.data.ok
        ? { dot: 'bg-success', text: `Server online · v${health.data.version}` }
        : { dot: 'bg-warning', text: 'Setup incomplete' }
  const problems = health.data?.problems ?? []
  const indicator = (
    <>
      <span className={cn('size-2 shrink-0 rounded-full', state.dot)} aria-hidden />
      <span>{state.text}</span>
    </>
  )
  if (problems.length === 0) {
    return <output className="text-muted flex items-center gap-2 text-xs">{indicator}</output>
  }
  // Setup problems are listed in full, not hidden in a hover tooltip: they
  // say exactly what to fix (e.g. a missing token), on any device.
  return (
    <details className="text-muted text-xs">
      <summary className="hover:text-fg flex cursor-pointer items-center gap-2">
        {indicator}
        <span className="sr-only">: show the problems</span>
      </summary>
      <ul className="mt-2 list-disc space-y-1 pl-5 break-words">
        {problems.map((problem) => (
          <li key={problem}>{problem}</li>
        ))}
      </ul>
    </details>
  )
}

function CurrentJob() {
  const { data: job } = useCurrentJob()
  if (!job || !isJobActive(job)) return null
  const target = job.kind === 'live' ? '/live' : `/runs/${encodeURIComponent(job.run_id)}`
  return (
    <Link
      to={target}
      className="ring-border hover:bg-subtle flex min-w-0 items-center gap-2 rounded-full py-1 pr-3 pl-1.5 text-xs ring-1"
    >
      <JobStateBadge state={job.state} />
      <span className="text-fg truncate">
        {job.kind === 'live' ? 'Live recording' : job.kind === 'resume' ? 'Resuming' : 'Processing'}
      </span>
    </Link>
  )
}

const THEME_CYCLE: Record<ThemePreference, ThemePreference> = {
  system: 'light',
  light: 'dark',
  dark: 'system',
}

function ThemeToggle() {
  const [theme, setTheme] = useTheme()
  const Icon = theme === 'light' ? Sun : theme === 'dark' ? Moon : Monitor
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => setTheme(THEME_CYCLE[theme])}
      aria-label={`Theme: ${theme}. Switch to ${THEME_CYCLE[theme]}`}
      title={`Theme: ${theme}`}
    >
      <Icon aria-hidden />
    </Button>
  )
}

function SidebarFooter() {
  return (
    <div className="space-y-3">
      <HealthIndicator />
      <ThemeToggle />
    </div>
  )
}

function Brand() {
  return (
    <Link to="/" className="flex items-center gap-2.5 rounded-md">
      <img src="/favicon.svg" alt="" width={28} height={28} className="size-7" />
      <span className="text-fg font-semibold" translate="no">
        Meeting Assistant
      </span>
    </Link>
  )
}

export function AppShell({ children }: { children?: ReactNode }) {
  // The menu remembers the page it was opened on, so navigating anywhere
  // closes it without an effect.
  const location = useLocation()
  const [menuOpenOn, setMenuOpenOn] = useState<string | null>(null)
  const menuOpen = menuOpenOn === location.pathname
  const setMenuOpen = (open: boolean) => setMenuOpenOn(open ? location.pathname : null)

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15rem_1fr]">
      <a
        href="#main"
        className="bg-accent text-accent-fg sr-only z-50 rounded-md px-3 py-2 focus-visible:not-sr-only focus-visible:fixed focus-visible:top-2 focus-visible:left-2"
      >
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside className="border-border bg-surface sticky top-0 hidden h-dvh flex-col justify-between border-r p-4 lg:flex">
        <div className="space-y-6">
          <Brand />
          <Navigation />
        </div>
        <SidebarFooter />
      </aside>

      <div className="min-w-0">
        <header className="border-border bg-surface/90 sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b px-4 backdrop-blur sm:px-6">
          <div className="flex items-center gap-2 lg:hidden">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setMenuOpen(!menuOpen)}
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            >
              {menuOpen ? <X aria-hidden /> : <Menu aria-hidden />}
            </Button>
            <Brand />
          </div>
          <div className="hidden lg:block" />
          <CurrentJob />
        </header>

        {menuOpen ? (
          <div
            id="mobile-nav"
            className="border-border bg-surface space-y-6 border-b p-4 lg:hidden"
          >
            <Navigation onNavigate={() => setMenuOpen(false)} />
            <SidebarFooter />
          </div>
        ) : null}

        <main
          id="main"
          // Focus target for the skip link only (never reached by Tab), so no
          // focus ring is needed here.
          tabIndex={-1}
          className="mx-auto max-w-6xl px-4 py-6 outline-none sm:px-6 lg:py-8"
        >
          {children ?? <Outlet />}
        </main>
      </div>
    </div>
  )
}

export function PageHeader({
  title,
  description,
  actions,
  children,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-fg text-2xl font-semibold tracking-tight text-balance break-words">
          {title}
        </h1>
        {description ? <div className="text-muted mt-1 text-sm">{description}</div> : null}
        {children}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}
