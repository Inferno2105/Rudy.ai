/**
 * The API token, held for the browser session.
 *
 * Stored in sessionStorage by default (gone when the tab closes); "remember
 * on this device" moves it to localStorage. Either store can be unavailable
 * (private windows, blocked site data), so every access is guarded and the
 * in-memory copy is what the app actually uses.
 *
 * A token is never put in a URL. Requests carry it in the Authorization
 * header; audio playback uses a short-lived, run-scoped ticket the server
 * issues instead (see `api/client.ts#audioUrl`).
 */
import { useSyncExternalStore } from 'react'

const KEY = 'meeting-assistant.api-token'

export type ClearReason = 'signed-out' | 'rejected'

interface TokenState {
  token: string | null
  /** Why the token was last cleared, so the gate can explain a sudden sign-out. */
  clearedBecause: ClearReason | null
}

function readStored(): string | null {
  for (const store of [() => window.sessionStorage, () => window.localStorage]) {
    try {
      const value = store().getItem(KEY)
      if (value) return value
    } catch {
      // Storage blocked: fall through to the next store, then to "no token".
    }
  }
  return null
}

function writeStored(token: string | null, remember: boolean): void {
  for (const [store, keep] of [
    [() => window.sessionStorage, token !== null && !remember],
    [() => window.localStorage, token !== null && remember],
  ] as const) {
    try {
      if (keep && token !== null) store().setItem(KEY, token)
      else store().removeItem(KEY)
    } catch {
      // Storage blocked: the token still lives in memory for this page.
    }
  }
}

let state: TokenState = { token: readStored(), clearedBecause: null }
const listeners = new Set<() => void>()

function emit(next: TokenState): void {
  state = next
  for (const listener of listeners) listener()
}

export function getToken(): string | null {
  return state.token
}

export function setToken(token: string, remember: boolean): void {
  writeStored(token, remember)
  emit({ token, clearedBecause: null })
}

export function clearToken(reason: ClearReason): void {
  if (state.token === null && state.clearedBecause === reason) return
  writeStored(null, false)
  emit({ token: null, clearedBecause: reason })
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useTokenState(): TokenState {
  return useSyncExternalStore(subscribe, () => state)
}

/** Test hook: reset the module's in-memory state. */
export function resetTokenForTests(): void {
  state = { token: readStored(), clearedBecause: null }
}
