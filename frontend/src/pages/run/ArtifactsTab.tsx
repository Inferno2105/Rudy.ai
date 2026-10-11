import { ChevronDown, Download } from 'lucide-react'
import { useSearchParams } from 'react-router'

import { useArtifact } from '../../api/queries'
import type { ArtifactName, RunDetail } from '../../api/types'
import { ErrorState } from '../../components/states'
import { Button } from '../../components/ui/button'
import { Card, CardHeader } from '../../components/ui/card'
import { EmptyState, LoadingBlock } from '../../components/ui/feedback'
import { useToast } from '../../components/ui/toast-context'
import { stageLabel } from '../../lib/stages'
import { cn } from '../../lib/utils'

/** Expanded panels live in the URL (`?open=a,b`), so the view can be linked. */
const OPEN_PARAM = 'open'

function ArtifactRow({
  runId,
  name,
  open,
  onToggle,
}: {
  runId: string
  name: ArtifactName
  open: boolean
  onToggle: () => void
}) {
  const artifact = useArtifact(runId, name, open)
  const notify = useToast()
  const panelId = `artifact-${name}`

  async function download() {
    // Fetched with the token and saved from memory: a plain link to the API
    // could not carry the Authorization header.
    const data = artifact.data !== undefined ? artifact.data : (await artifact.refetch()).data
    if (data === undefined) {
      notify({
        tone: 'danger',
        title: `Could not download ${name}`,
        description:
          artifact.error instanceof Error
            ? `${artifact.error.message}. Try again, or check that the server is running.`
            : 'The server did not return it. Try again, or check that the server is running.',
      })
      return
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${runId}_${name}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <li>
      <div className="flex items-center gap-3 px-5 py-3">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          className="hover:text-accent flex min-w-0 flex-1 items-center gap-2 text-left text-sm"
        >
          <ChevronDown
            className={cn('text-muted size-4 shrink-0 transition-transform', open && 'rotate-180')}
            aria-hidden
          />
          <span className="text-fg font-medium">{stageLabel(name)}</span>
          <code translate="no" className="text-faint truncate font-mono text-xs">
            {name}
          </code>
        </button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => void download()}
          aria-label={`Download ${name} JSON`}
        >
          <Download aria-hidden /> JSON
        </Button>
      </div>
      {open ? (
        <div id={panelId} className="px-5 pb-4">
          {artifact.isPending ? (
            <LoadingBlock label={`Loading ${name}…`} lines={3} />
          ) : artifact.isError ? (
            <ErrorState error={artifact.error} onRetry={() => void artifact.refetch()} />
          ) : (
            // Focusable so the JSON can be scrolled with the keyboard.
            <section
              tabIndex={0}
              aria-label={`${name} JSON`}
              className="bg-subtle max-h-96 overflow-auto overscroll-contain rounded-lg"
            >
              <pre translate="no" className="text-fg p-4 font-mono text-xs leading-relaxed">
                {JSON.stringify(artifact.data, null, 2)}
              </pre>
            </section>
          )}
        </div>
      ) : null}
    </li>
  )
}

export function ArtifactsTab({ run }: { run: RunDetail }) {
  const [params, setParams] = useSearchParams()
  const openNames = new Set((params.get(OPEN_PARAM) ?? '').split(',').filter(Boolean))

  function toggle(name: string) {
    const next = new Set(openNames)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    const updated = new URLSearchParams(params)
    if (next.size) updated.set(OPEN_PARAM, [...next].join(','))
    else updated.delete(OPEN_PARAM)
    setParams(updated, { replace: true })
  }

  return (
    <Card>
      <CardHeader
        title="Artifacts"
        description="Each stage's output exactly as written to the run directory, in pipeline order."
      />
      {run.artifacts.length === 0 ? (
        <EmptyState title="No artifacts yet">Nothing has been written for this run.</EmptyState>
      ) : (
        <ul className="divide-border divide-y">
          {run.artifacts.map((name) => (
            <ArtifactRow
              key={name}
              runId={run.run_id}
              name={name as ArtifactName}
              open={openNames.has(name)}
              onToggle={() => toggle(name)}
            />
          ))}
        </ul>
      )}
    </Card>
  )
}
