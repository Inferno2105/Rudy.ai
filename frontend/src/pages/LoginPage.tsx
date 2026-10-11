import { ArrowLeft, Eye, EyeOff, LogIn, ShieldCheck, UserPlus } from 'lucide-react'
import { motion } from 'motion/react'
import { useRef, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'

import { ApiError } from '../api/client'
import { useAuthStatus, useHealth, useLogin, useSetup } from '../api/queries'
import { SunsetScene } from '../components/art'
import { Button } from '../components/ui/button'
import { Callout, LoadingBlock } from '../components/ui/feedback'
import { Field, Input } from '../components/ui/field'
import { BrandMark } from '../components/visuals'
import { EASE_OUT } from '../lib/easing'
import { useDocumentTitle } from '../lib/utils'

/** Where to go after signing in: the page that sent us here, if it is ours. */
function safeNext(raw: string | null): string {
  return raw && raw.startsWith('/') && !raw.startsWith('//') ? raw : '/meetings'
}

function PasswordInput({
  id,
  describedBy,
  value,
  onChange,
  autoComplete,
  invalid,
  inputRef,
}: {
  id: string
  describedBy: string | undefined
  value: string
  onChange: (value: string) => void
  autoComplete: string
  invalid: boolean
  inputRef?: React.Ref<HTMLInputElement>
}) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="relative">
      <Input
        ref={inputRef}
        id={id}
        name="password"
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        type={visible ? 'text' : 'password'}
        autoComplete={autoComplete}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 pr-11"
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        className="text-muted hover:text-fg absolute top-1/2 right-2 -translate-y-1/2 rounded p-1.5"
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
      >
        {visible ? (
          <EyeOff className="size-4" aria-hidden />
        ) : (
          <Eye className="size-4" aria-hidden />
        )}
      </button>
    </div>
  )
}

function SignInForm({ setup, next }: { setup: boolean; next: string }) {
  const navigate = useNavigate()
  const login = useLogin()
  const create = useSetup()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const usernameRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const pending = login.isPending || create.isPending

  function fail(message: string, field: 'username' | 'password') {
    setError(message)
    ;(field === 'username' ? usernameRef : passwordRef).current?.focus()
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (!username.trim()) return fail('Enter your username.', 'username')
    if (!password) return fail('Enter your password.', 'password')
    if (setup && password !== confirm) return fail('The two passwords do not match.', 'password')
    const body = { username: username.trim(), password }
    const done = () => navigate(next, { replace: true })
    const onError = (err: Error) =>
      fail(
        err instanceof ApiError && err.status === 0
          ? 'The server could not be reached. Is `meeting-assistant serve` running?'
          : err.message,
        'password',
      )
    if (setup) create.mutate(body, { onSuccess: done, onError })
    else login.mutate(body, { onSuccess: done, onError })
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <Field
        label="Username"
        hint={setup ? '3–32 letters, digits, dots, dashes or underscores.' : undefined}
      >
        {({ id, describedBy }) => (
          <Input
            ref={usernameRef}
            id={id}
            name="username"
            aria-describedby={describedBy}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className="h-11"
          />
        )}
      </Field>
      <Field label="Password" hint={setup ? 'At least 8 characters.' : undefined}>
        {({ id, describedBy }) => (
          <PasswordInput
            inputRef={passwordRef}
            id={id}
            describedBy={describedBy}
            value={password}
            onChange={setPassword}
            autoComplete={setup ? 'new-password' : 'current-password'}
            invalid={Boolean(error)}
          />
        )}
      </Field>
      {setup ? (
        <Field label="Confirm password">
          {({ id, describedBy }) => (
            <PasswordInput
              id={id}
              describedBy={describedBy}
              value={confirm}
              onChange={setConfirm}
              autoComplete="new-password"
              invalid={Boolean(error)}
            />
          )}
        </Field>
      ) : null}

      {error ? (
        <Callout tone="danger" announce="alert">
          {error}
        </Callout>
      ) : null}

      <Button type="submit" variant="primary" className="h-11 w-full text-base" disabled={pending}>
        {setup ? <UserPlus aria-hidden /> : <LogIn aria-hidden />}
        {pending ? 'Signing in…' : setup ? 'Create account' : 'Sign in'}
      </Button>
    </form>
  )
}

export function LoginPage() {
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const status = useAuthStatus()
  const health = useHealth()
  const setup = status.data?.setup_required ?? false
  useDocumentTitle(setup ? 'Create your account' : 'Sign in')

  if (status.data?.user) return <Navigate to={next} replace />

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      {/* Illustration panel (decorative; hidden on small screens). */}
      <aside className="relative hidden overflow-hidden lg:block" aria-hidden>
        <div className="absolute inset-0">
          <SunsetScene bubbles={false} />
        </div>
        <div className="relative flex h-full flex-col justify-between p-10">
          <div className="flex items-center gap-3">
            <BrandMark />
            <span className="font-display text-fg text-lg font-semibold">Meeting Assistant</span>
          </div>
          <motion.blockquote
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.3, ease: EASE_OUT }}
            className="glass max-w-md rounded-2xl p-6"
          >
            <p className="font-display text-fg text-xl leading-snug">
              “Every voice in the room, in every language they speak, captured and understood.”
            </p>
            <p className="text-muted mt-3 text-sm">
              Hindi · English · Hinglish, on your own machine.
            </p>
          </motion.blockquote>
        </div>
      </aside>

      <main id="main" className="relative flex items-center justify-center px-5 py-12 sm:px-10">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE_OUT }}
          className="w-full max-w-sm"
        >
          <Link
            to="/"
            className="text-muted hover:text-fg group mb-10 inline-flex items-center gap-1 text-sm"
          >
            <ArrowLeft
              className="size-4 transition-transform group-hover:-translate-x-0.5"
              aria-hidden
            />
            Back to home
          </Link>
          <div className="mb-8 lg:hidden">
            <BrandMark className="size-11" />
          </div>
          <h1 className="text-brand text-3xl font-semibold tracking-tight">
            {setup ? 'Create your account' : 'Welcome back'}
          </h1>
          <p className="text-muted mt-2 text-sm">
            {setup
              ? 'This is the first sign-in on this server, so this account will be its first user.'
              : 'Sign in to open your meetings.'}
          </p>

          <div className="mt-8">
            {status.isPending ? (
              <LoadingBlock label="Checking the server…" lines={3} />
            ) : status.isError ? (
              <Callout tone="danger" title="The server could not be reached" announce="alert">
                Start it with <code translate="no">meeting-assistant serve</code>, then reload this
                page.
              </Callout>
            ) : (
              <SignInForm setup={setup} next={next} />
            )}
          </div>

          <p className="text-faint mt-8 flex items-start gap-2 text-xs">
            <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              Passwords are stored hashed (scrypt); your session is a secure cookie scripts cannot
              read. More accounts:{' '}
              <code translate="no" className="font-mono">
                meeting-assistant users add
              </code>
              .
            </span>
          </p>
          <output className="text-faint mt-3 block text-xs">
            {health.isError
              ? 'Server unreachable'
              : health.data
                ? `Server v${health.data.version}`
                : ''}
          </output>
        </motion.div>
      </main>
    </div>
  )
}
