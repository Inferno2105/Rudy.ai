# Frontend

The web UI for the meeting assistant: React 19 + Vite + TypeScript, Tailwind CSS
and Radix primitives, talking to the FastAPI backend under `/api`.

In production the backend serves the built UI itself (`meeting-assistant serve`
serves `frontend/dist` at `/`), so there is one origin, one port and no CORS.

## Setup

Requires Node 22+.

```powershell
cd frontend
npm install
npm run build      # then `meeting-assistant serve` serves it
```

## Development

```powershell
meeting-assistant serve            # backend on :8000
npm run dev                        # UI on :5173, proxying /api to :8000
```

Set `VITE_API_TARGET` to proxy to a backend elsewhere.

| Command             | What it does                                                                     |
| ------------------- | -------------------------------------------------------------------------------- |
| `npm run check`     | everything below except e2e: API types, typecheck, lint, format, tests           |
| `npm run gen:api`   | regenerate `src/api/schema.d.ts` from `src/api/openapi.json`                     |
| `npm run check:api` | fail if `schema.d.ts` is stale                                                   |
| `npm run typecheck` | `tsc -b` (strict, `noUncheckedIndexedAccess`)                                    |
| `npm run lint`      | oxlint, including the React-hooks and jsx-a11y rules                             |
| `npm test`          | Vitest + Testing Library + MSW                                                   |
| `npm run e2e`       | Playwright against the real backend with a stub pipeline (`npm run build` first) |

## The API contract is generated, never hand-written

1. `meeting-assistant openapi` writes the backend's schema to `src/api/openapi.json`.
2. `npm run gen:api` turns it into `src/api/schema.d.ts`.
3. `src/api/client.ts` is an `openapi-fetch` client over those types, so every
   path, parameter and response body is checked at compile time.

Both directions are guarded: a backend test fails if the committed
`openapi.json` differs from the live schema, and `check:api` fails if
`schema.d.ts` is stale. Test fixtures (`src/test/fixtures.ts`) are typed
against the same schema, so a response-shape change breaks the tests rather
than leaving them testing a contract the server no longer has.

## Design notes

- **Accounts.** Sign-in sets an HttpOnly session cookie the browser sends with
  every same-origin request (including `<audio>` and the event stream), so no
  code handles credentials. Any 401 from a data endpoint re-checks
  `/api/auth/status`, and the route guard sends the user to `/login?next=…`.
- **Routes.** `/` is the public landing page, `/login` signs in (or creates the
  first account); the app lives under `/meetings`, `/new`, `/live`, `/runs/:id`
  and `/evaluation`.
- **Progress over SSE.** `src/api/sse.ts` reads the `/events` stream with
  `fetch` and parses it itself, for an explicit abort on unmount, a chosen
  backoff and a clean stop on `end`. Segments are spliced by their
  `start_index`, so a reconnect (where the server replays from zero) never
  duplicates them.
- **Audio playback** streams `GET /runs/{id}/audio` directly; the server
  supports Range requests, so seeking works.
- **Absent is not empty.** A 404 for an artifact renders as "not produced", with
  the stage's recorded error, never as an empty summary or table.
- **Numbers are displayed, not computed.** Evaluation metrics are shown exactly
  as the harness wrote them, and each clip links to the run it was scored on.
- **Offline.** Fonts (Inter, Noto Sans Devanagari) are bundled; nothing loads
  from a CDN, and the page's Content-Security-Policy is `default-src 'self'`.

## Layout

```
src/
  api/          openapi.json, schema.d.ts (generated), client, queries, SSE
  components/   app shell, transcript, stage progress, audio player; ui/ primitives
  pages/        Meetings, New run, Run detail (tabs), Live, Evaluation
  lib/          formatting, speaker colours, language tags, stage helpers
  test/         MSW server, typed fixtures, render helper
e2e/            Playwright spec (server: backend/tests/e2e_server.py)
```
