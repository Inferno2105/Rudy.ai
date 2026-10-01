/**
 * The typed API client.
 *
 * `openapi-fetch` over the generated `paths` type: every path, parameter and
 * response body is checked at compile time against the backend's schema.
 * A middleware attaches the token and turns a 401 into a sign-out, so an
 * expired or rotated token always lands the user back on the token screen
 * instead of a page full of failed requests.
 */
import createClient, { type Middleware } from 'openapi-fetch'

import { clearToken, getToken } from '../auth/token'
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

export function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function handleUnauthorized(status: number): void {
  if (status === 401 && getToken() !== null) clearToken('rejected')
}

const auth: Middleware = {
  onRequest({ request }) {
    const token = getToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
  onResponse({ response }) {
    handleUnauthorized(response.status)
    return response
  },
}

export const api = createClient<paths>({
  baseUrl: window.location.origin,
  // Resolve fetch per call rather than capturing it at import time, so
  // anything that wraps fetch later (request mocking in tests, devtools) applies.
  fetch: (request) => globalThis.fetch(request),
})
api.use(auth)

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

/** Raw fetch with the token, for the few responses that are not JSON models. */
export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response
  try {
    response = await fetch(apiUrl(path), {
      ...init,
      headers: { ...authHeaders(), ...(init.headers as Record<string, string> | undefined) },
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, errorMessage(null, 0))
  }
  handleUnauthorized(response.status)
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    throw new ApiError(response.status, errorMessage(body, response.status))
  }
  return response
}

/** A raw artifact, exactly as the pipeline wrote it. */
export async function fetchArtifact(runId: string, name: ArtifactName): Promise<unknown> {
  const response = await authFetch(
    `/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(name)}`,
  )
  return response.json() as Promise<unknown>
}

/**
 * A playable URL for a run's recording. `<audio>` cannot send headers, so
 * the server issues a short-lived ticket scoped to this run's audio.
 */
export async function audioUrl(runId: string): Promise<{ url: string; expiresAt: number }> {
  const data = await unwrap(
    api.POST('/api/runs/{run_id}/audio-url', { params: { path: { run_id: runId } } }),
  )
  return { url: apiUrl(data.url), expiresAt: data.expires_at }
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
    for (const [name, value] of Object.entries(authHeaders())) xhr.setRequestHeader(name, value)
    xhr.responseType = 'json'
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total)
    }
    xhr.onload = () => {
      handleUnauthorized(xhr.status)
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
