import '@testing-library/jest-dom/vitest'

import { cleanup, configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest'

import { resetTokenForTests } from '../auth/token'
import { server } from './server'

// Lazily loaded routes are transformed on first import under Vitest, which
// can take longer than Testing Library's 1 s default on a cold run.
configure({ asyncUtilTimeout: 5_000 })

// jsdom lacks these browser APIs; Radix and Recharts need them to exist.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
window.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList
Element.prototype.scrollIntoView ??= () => {}
HTMLMediaElement.prototype.play = () => Promise.resolve()
HTMLMediaElement.prototype.pause = () => {}
HTMLMediaElement.prototype.load = () => {}

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  window.sessionStorage.clear()
  window.localStorage.clear()
  resetTokenForTests()
})
afterEach(() => {
  cleanup()
  server.resetHandlers()
})
afterAll(() => server.close())
