import { useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, KeyRound } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'

import { apiUrl } from '../api/client'
import { useHealth } from '../api/queries'
import { Button } from '../components/ui/button'
import { Callout } from '../components/ui/feedback'
import { Field, Input, Switch } from '../components/ui/field'
import { setToken, useTokenState } from './token'

/** Check a candidate token against a protected route before accepting it. */
async function verifyToken(token: string): Promise<'ok' | 'rejected' | 'unreachable'> {
  try {
    const response = await fetch(apiUrl('/api/jobs/current'), {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (response.status === 401) return 'rejected'
    return response.ok ? 'ok' : 'unreachable'
  } catch {
    return 'unreachable'
  }
}

function TokenForm() {
  const { clearedBecause } = useTokenState()
  const health = useHealth()
  const [value, setValue] = useState('')
  const [remember, setRemember] = useState(false)
  const [visible, setVisible] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  function fail(message: string) {
    setError(message)
    input.current?.focus()
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    const token = value.trim()
    if (!token) {
      fail('Enter the API token.')
      return
    }
    setChecking(true)
    setError(null)
    const result = await verifyToken(token)
    setChecking(false)
    if (result === 'ok') setToken(token, remember)
    else if (result === 'rejected') {
      fail(
        "That token was not accepted by the server. Check the API_TOKEN line in the server's .env file.",
      )
    } else fail('The server could not be reached. Is `meeting-assistant serve` running?')
  }

  return (
    <main id="main" className="flex min-h-dvh items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <img src="/favicon.svg" alt="" width={40} height={40} className="size-10" />
          <div>
            <h1 className="text-fg text-xl font-semibold" translate="no">
              Meeting Assistant
            </h1>
            <p className="text-muted text-sm">Hindi–English meeting transcription and analysis</p>
          </div>
        </div>
        <form
          onSubmit={submit}
          className="bg-surface ring-border space-y-5 rounded-xl p-6 shadow-sm ring-1"
          noValidate
        >
          <div>
            <h2 className="text-fg flex items-center gap-2 font-medium">
              <KeyRound className="text-accent size-4" aria-hidden /> Enter the API token
            </h2>
            <p className="text-muted mt-1 text-sm">
              This server requires the token set as{' '}
              <code translate="no" className="font-mono">
                API_TOKEN
              </code>{' '}
              in its{' '}
              <code translate="no" className="font-mono">
                .env
              </code>{' '}
              file.
            </p>
          </div>

          {clearedBecause === 'rejected' ? (
            <Callout tone="warning" announce="status">
              The server rejected the saved token (it may have been changed). Enter it again.
            </Callout>
          ) : null}

          <Field label="API token" error={error}>
            {({ id, describedBy }) => (
              <div className="relative">
                <Input
                  ref={input}
                  id={id}
                  name="api_token"
                  aria-describedby={describedBy}
                  aria-invalid={error ? true : undefined}
                  type={visible ? 'text' : 'password'}
                  autoComplete="current-password"
                  spellCheck={false}
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                  className="pr-10 font-mono"
                />
                <button
                  type="button"
                  onClick={() => setVisible((v) => !v)}
                  className="text-muted hover:text-fg absolute top-1/2 right-2 -translate-y-1/2 rounded p-1"
                  aria-label={visible ? 'Hide token' : 'Show token'}
                  aria-pressed={visible}
                >
                  {visible ? (
                    <EyeOff className="size-4" aria-hidden />
                  ) : (
                    <Eye className="size-4" aria-hidden />
                  )}
                </button>
              </div>
            )}
          </Field>

          <Switch
            checked={remember}
            onCheckedChange={setRemember}
            label="Remember on this device"
            description="Otherwise the token is forgotten when this tab closes."
          />

          <Button type="submit" variant="primary" className="w-full" disabled={checking}>
            {checking ? 'Checking…' : 'Continue'}
          </Button>
        </form>

        <output className="text-muted mt-4 block text-center text-xs">
          {health.isPending
            ? 'Contacting server…'
            : health.isError
              ? 'Server unreachable'
              : `Server online · v${health.data.version}${health.data.ok ? '' : ' · setup incomplete'}`}
        </output>
      </div>
    </main>
  )
}

/** Renders children only once a token is held; otherwise asks for one. */
export function TokenGate({ children }: { children: ReactNode }) {
  const { token } = useTokenState()
  const queryClient = useQueryClient()
  // Drop everything cached under the old token, so a different user's data
  // (or a wall of 401s) never shows after signing back in.
  useEffect(() => {
    if (!token) queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'health' })
  }, [token, queryClient])
  return token ? <>{children}</> : <TokenForm />
}
