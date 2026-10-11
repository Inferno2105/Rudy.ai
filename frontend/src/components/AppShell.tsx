import { BarChart3, ListMusic, Menu, Mic, Monitor, Moon, Sun, Upload, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation, useOutlet } from 'react-router'

import { useCurrentJob, useHealth } from '../api/queries'
import { isJobActive } from '../api/types'
import { useTheme, type ThemePreference } from '../lib/theme'
import { EASE_OUT } from '../lib/easing'
import { cn } from '../lib/utils'
import { JobStateBadge } from './status'
import { Button } from './ui/button'
import { BrandMark, Equalizer } from './visuals'

const NAV = [
  { to: '/', label: 'Meetings', icon: ListMusic, end: true },
  { to: '/new', label: 'New run', icon: Upload, end: false },
  { to: '/live', label: 'Live', icon: Mic, end: false },
  { to: '/evaluation', label: 'Evaluation', icon: BarChart3, end: false },
]

function Navigation({ id, onNavigate }: { id: string; onNavigate?: () => void }) {
  return (
    <nav aria-label="Main">
      <ul className="space-y-1">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  'relative flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors',
                  isActive ? 'text-fg' : 'text-muted hover:text-fg hover:bg-subtle',
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive ? (
                    // Slides between items as the page changes.
                    <motion.span
                      layoutId={id}
                      aria-hidden
                      className="bg-accent-soft ring-accent/25 absolute inset-0 rounded-xl ring-1 ring-inset"
                      transition={{ type: 'spring', stiffness: 420, damping: 36 }}
                    />
                  ) : null}
                  <Icon className={cn('relative size-4', isActive && 'text-accent')} aria-hidden />
                  <span className="relative">{label}</span>
                </>
              )}
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
      <span className="relative flex size-2 shrink-0" aria-hidden>
        {health.isSuccess && health.data.ok ? (
          <span className="bg-success animate-ring absolute inset-0 rounded-full" />
        ) : null}
        <span className={cn('relative size-2 rounded-full', state.dot)} />
      </span>
      <span>{state.text}</span>
    </>
  )
  if (problems.length === 0) {
    return <output className="text-muted flex items-center gap-2 text-xs">{indicator}</output>
  }
  // Setup problems are listed in full, not hidden in a hover tooltip: they
  // say exactly what to fix (e.g. a missing model token), on any device.
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
  const active = job && isJobActive(job) ? job : null
  return (
    <AnimatePresence>
      {active ? (
        <motion.div
          key={active.job_id}
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.25, ease: EASE_OUT }}
        >
          <Link
            to={active.kind === 'live' ? '/live' : `/runs/${encodeURIComponent(active.run_id)}`}
            className="glass hover:border-strong-border flex min-w-0 items-center gap-2 rounded-full py-1 pr-3 pl-1.5 text-xs transition-colors"
          >
            <JobStateBadge state={active.state} />
            <Equalizer className="text-accent h-3" />
            <span className="text-fg truncate">
              {active.kind === 'live'
                ? 'Live recording'
                : active.kind === 'resume'
                  ? 'Resuming'
                  : 'Processing'}
            </span>
          </Link>
        </motion.div>
      ) : null}
    </AnimatePresence>
  )
}

const THEME_CYCLE: Record<ThemePreference, ThemePreference> = {
  dark: 'light',
  light: 'system',
  system: 'dark',
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
    >
      <motion.span
        key={theme}
        initial={{ rotate: -90, opacity: 0 }}
        animate={{ rotate: 0, opacity: 1 }}
        transition={{ duration: 0.3, ease: EASE_OUT }}
        className="inline-flex"
      >
        <Icon aria-hidden />
      </motion.span>
      <span className="capitalize">{theme}</span>
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
    <Link to="/" className="flex items-center gap-2.5 rounded-lg">
      <BrandMark />
      <span className="font-display text-fg leading-tight font-semibold" translate="no">
        Meeting
        <br />
        <span className="text-muted text-sm font-medium">Assistant</span>
      </span>
    </Link>
  )
}

/** The routed page, faded and lifted in when the route changes. */
function AnimatedOutlet() {
  const location = useLocation()
  const outlet = useOutlet()
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={location.pathname}
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -6, transition: { duration: 0.12 } }}
        transition={{ duration: 0.35, ease: EASE_OUT }}
      >
        {outlet}
      </motion.div>
    </AnimatePresence>
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
    <div className="min-h-dvh lg:grid lg:grid-cols-[16rem_1fr]">
      <a
        href="#main"
        className="bg-accent text-accent-fg sr-only z-50 rounded-md px-3 py-2 focus-visible:not-sr-only focus-visible:fixed focus-visible:top-2 focus-visible:left-2"
      >
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh p-3 lg:block">
        <div className="glass flex h-full flex-col justify-between rounded-2xl p-4">
          <div className="space-y-8">
            <Brand />
            <Navigation id="nav-desktop" />
          </div>
          <SidebarFooter />
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 px-4 backdrop-blur-xl sm:px-6 lg:bg-transparent">
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

        <AnimatePresence>
          {menuOpen ? (
            <motion.div
              id="mobile-nav"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.25, ease: EASE_OUT }}
              className="overflow-hidden lg:hidden"
            >
              <div className="glass mx-3 mb-3 space-y-6 rounded-2xl p-4">
                <Navigation id="nav-mobile" onNavigate={() => setMenuOpen(false)} />
                <SidebarFooter />
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>

        <main
          id="main"
          // Focus target for the skip link only (never reached by Tab), so no
          // focus ring is needed here.
          tabIndex={-1}
          className="mx-auto max-w-6xl px-4 pt-2 pb-12 outline-none sm:px-6 lg:pt-4"
        >
          {children ?? <AnimatedOutlet />}
        </main>
      </div>
    </div>
  )
}

export function PageHeader({
  title,
  eyebrow,
  description,
  actions,
  children,
}: {
  title: ReactNode
  eyebrow?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? (
          <p className="text-accent mb-2 text-xs font-semibold tracking-[0.18em] uppercase">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="text-brand text-3xl font-semibold tracking-tight text-balance break-words sm:text-4xl">
          {title}
        </h1>
        {description ? <div className="text-muted mt-2 text-sm">{description}</div> : null}
        {children}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}
