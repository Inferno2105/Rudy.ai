# Frontend (not yet implemented)

Placeholder. The UI is built in a later phase, deliberately after the backend
pipeline is proven end to end and the REST API is in place.

## Planned

**React + Vite + TypeScript**, consuming the FastAPI backend. The API client is
**generated from the backend's exported OpenAPI schema** rather than hand-written,
so the types cannot drift from the server.

Views:

- **Meetings** — list of runs from the SQLite index, filterable by date, speaker
  count and language mix.
- **Meeting detail** — transcript with per-speaker colouring and language tags,
  the summary, action items, and speaker participation charts.
- **Live** — start a microphone session and watch segments arrive as chunks are
  processed, over SSE or a WebSocket.
- **Evaluation** — the metric tables and figures from the evaluation study.

## Why the scaffold is not committed yet

Running `npm create vite@latest` at implementation time produces a correct,
current scaffold. A hand-written `package.json`, `tsconfig.json` and
`vite.config.ts` sitting here unused for several phases would only drift out of
date and would have to be replaced anyway.

What actually needed to happen early is the part that constrains the backend, and
it has: every pipeline stage returns data structures rather than printing, no
business logic lives in a `__main__` block, and each run's artifacts follow a
stable documented JSON contract. That is what makes this layer cheap to add —
see `docs/artifact-contract.md`.

## Setup, when the time comes

```powershell
cd frontend
npm install
npm run dev        # expects the backend on http://localhost:8000
```
