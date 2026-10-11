/**
 * The typed API client.
 *
 * `openapi-fetch` over the generated `paths` type: every path, parameter and
 * response body is checked at compile time against the backend's schema.
 * The session is an HttpOnly cookie the browser sends with every same-origin
 * request, so no code here handles credentials. When any request comes back
 * 401 (signed out elsewhere, session expired) the registered handler runs,
 * which sends the user to the sign-in page.
 */
import createClient, { type Middleware } from 'openapi-fetch'

import type { paths } from './schema'
import type { ArtifactName, UploadResult } from './types'

/** Absolute URL for an API path. Relative URLs are not valid outside a page
 * (tests run under Node), and the API is always same-origin. */

export function apiUrl(path: string): string {
  return new URL(path, window.location.origin).toString()
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

/** FastAPI errors carry `detail` as a string, or a list of validation errors. */
export function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          item && typeof item === 'object' && 'msg' in item ? String(item.msg) : String(item),
        )
        .join('; ')
    }
  }
  return status === 0 ? 'The server could not be reached' : `Request failed (HTTP ${status})`
}

let onUnauthorized: () => void = () => {}

/** Called when the server says the session is gone (set once by the app). */
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

/** 401 from a data endpoint means "signed out". The sign-in endpoints answer
 * 401 for a wrong password, which is not that. */
export function noteStatus(status: number, url: string): void {
  if (status === 401 && !new URL(url, window.location.origin).pathname.startsWith('/api/auth/')) {
    onUnauthorized()
  }
}

const sessionWatch: Middleware = {
  onResponse({ request, response }) {
    noteStatus(response.status, request.url)
    return response
  },
}

export const api = createClient<paths>({
  baseUrl: window.location.origin,
  // Resolve fetch per call rather than capturing it at import time, so
  // anything that wraps fetch later (request mocking in tests, devtools) applies.
  fetch: (request) => globalThis.fetch(request),
})
api.use(sessionWatch)

interface FetchResult<T> {
  data?: T
  error?: unknown
  response: Response
}

/** Resolve an openapi-fetch call to its data, or throw an `ApiError`. */
export async function unwrap<T>(call: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>
  try {
    result = await call
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, errorMessage(null, 0))
  }
  if (result.error !== undefined || !result.response.ok) {
    throw new ApiError(result.response.status, errorMessage(result.error, result.response.status))
  }
  return result.data as T
}

/** Raw fetch for the few responses that are not JSON models. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response
  try {
    response = await fetch(apiUrl(path), init)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, errorMessage(null, 0))
  }
  noteStatus(response.status, response.url || apiUrl(path))
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    throw new ApiError(response.status, errorMessage(body, response.status))
  }
  return response
}

/** A raw artifact, exactly as the pipeline wrote it. */
export async function fetchArtifact(runId: string, name: ArtifactName): Promise<unknown> {
  const response = await apiFetch(
    `/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(name)}`,
  )
  return response.json() as Promise<unknown>
}

/** Where an `<audio>` element plays a run's recording from (supports seeking). */
export function audioUrl(runId: string): string {
  return apiUrl(`/api/runs/${encodeURIComponent(runId)}/audio`)
}

/**
 * Upload a recording with progress reporting. `fetch` cannot report upload
 * progress, so this one request uses XMLHttpRequest.
 */
export function uploadAudio(
  file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', apiUrl('/api/uploads'))
    xhr.responseType = 'json'
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total)
    }
    xhr.onload = () => {
      noteStatus(xhr.status, apiUrl('/api/uploads'))
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as UploadResult)
      else reject(new ApiError(xhr.status, errorMessage(xhr.response, xhr.status)))
    }
    xhr.onerror = () => reject(new ApiError(0, errorMessage(null, 0)))
    xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'))
    signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    const body = new FormData()
    body.append('file', file)
    xhr.send(body)
  })
}
