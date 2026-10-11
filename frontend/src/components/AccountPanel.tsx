import { KeyRound, LogOut } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { useAuthStatus, useChangePassword, useLogout } from '../api/queries'
import { Button } from './ui/button'
import { Dialog, DialogClose, DialogContent, DialogTrigger } from './ui/dialog'
import { Callout } from './ui/feedback'
import { Field, Input } from './ui/field'
import { useToast } from './ui/toast-context'

function ChangePasswordDialog() {
  const [open, setOpen] = useState(false)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const change = useChangePassword()
  const notify = useToast()

  function reset(nextOpen: boolean) {
    setOpen(nextOpen)
    if (!nextOpen) {
      setCurrent('')
      setNext('')
      setConfirm('')
      setError(null)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (next !== confirm) {
      setError('The new passwords do not match.')
      return
    }
    setError(null)
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          reset(false)
          notify({
            tone: 'success',
            title: 'Password changed',
            description: 'Other devices were signed out.',
          })
        },
        onError: (err) => setError(err.message),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogTrigger asChild>
        <button
          type="button"
          aria-label="Change password"
          className="text-faint hover:text-accent inline-flex items-center gap-1 text-[11px] whitespace-nowrap transition-colors"
        >
          <KeyRound className="size-3" aria-hidden /> Password
        </button>
      </DialogTrigger>
      <DialogContent
        title="Change your password"
        description="Other devices signed in to this account will be signed out."
      >
        <form onSubmit={submit} className="space-y-4" noValidate>
          <Field label="Current password">
            {({ id, describedBy }) => (
              <Input
                id={id}
                name="current_password"
                type="password"
                autoComplete="current-password"
                aria-describedby={describedBy}
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
              />
            )}
          </Field>
          <Field label="New password" hint="At least 8 characters.">
            {({ id, describedBy }) => (
              <Input
                id={id}
                name="new_password"
                type="password"
                autoComplete="new-password"
                aria-describedby={describedBy}
                value={next}
                onChange={(event) => setNext(event.target.value)}
              />
            )}
          </Field>
          <Field label="Repeat new password">
            {({ id, describedBy }) => (
              <Input
                id={id}
                name="confirm_password"
                type="password"
                autoComplete="new-password"
                aria-describedby={describedBy}
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
              />
            )}
          </Field>
          {error ? (
            <Callout tone="danger" announce="alert">
              {error}
            </Callout>
          ) : null}
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="ghost">Cancel</Button>
            </DialogClose>
            <Button type="submit" variant="primary" disabled={change.isPending}>
              {change.isPending ? 'Saving…' : 'Change password'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** The signed-in user, with sign-out and password change. */
export function AccountPanel() {
  const status = useAuthStatus()
  const logout = useLogout()
  const navigate = useNavigate()
  const user = status.data?.user
  if (!user) return null
  return (
    <div className="glass flex items-center gap-2.5 rounded-xl p-2.5">
      <span
        aria-hidden
        className="bg-cta text-cta-fg grid size-9 shrink-0 place-items-center rounded-full text-xs font-bold uppercase"
      >
        {user.username.slice(0, 2)}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-fg truncate text-sm font-medium" translate="no">
          {user.username}
        </p>
        <ChangePasswordDialog />
      </div>
      <Button
        variant="ghost"
        size="sm"
        aria-label="Sign out"
        title="Sign out"
        disabled={logout.isPending}
        onClick={() =>
          logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })
        }
      >
        <LogOut aria-hidden />
      </Button>
    </div>
  )
}
