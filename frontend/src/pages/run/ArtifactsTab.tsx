import { ChevronDown, Download } from 'lucide-react'
import { useState } from 'react'

import { useArtifact } from '../../api/queries'
import type { ArtifactName, RunDetail } from '../../api/types'
import { ErrorState } from '../../components/states'
import { stageLabel } from '../../lib/stages'
import { Button } from '../../components/ui/button'
import { Card, CardHeader } from '../../components/ui/card'
import { EmptyState, LoadingBlock } from '../../components/ui/feedback'
import { cn } from '../../lib/utils'

function ArtifactRow({ runId, name }: { runId: string; name: ArtifactName }) {
  const [open, setOpen] = useState(false)
  const artifact = useArtifact(runId, name, open)
  const panelId = `artifact-${name}`

  function download() {
    // Already fetched with the token; save the same JSON rather than linking
    // to the API (a plain link cannot carry the Authorization header).
    const save = (data: unknown) => {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${runId}_${name}.json`
      link.click()
      URL.revokeObjectURL(url)
    }
    if (artifact.data !== undefined) save(artifact.data)
    else void artifact.refetch().then((result) => result.data !== undefined && save(result.data))
  }

  return (
    <li>
      <div className="flex items-center gap-3 px-5 py-3">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={panelId}
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
        <Button size="sm" variant="ghost" onClick={download} aria-label={`Download ${name} JSON`}>
          <Download aria-hidden /> JSON
        </Button>
      </div>
      {open ? (
        <div id={panelId} className="px-5 pb-4">
          {artifact.isPending ? (
            <LoadingBlock label={`Loading ${name}`} lines={3} />
          ) : artifact.isError ? (
            <ErrorState error={artifact.error} />
          ) : (
            <pre className="bg-subtle text-fg max-h-96 overflow-auto rounded-lg p-4 font-mono text-xs leading-relaxed">
              {JSON.stringify(artifact.data, null, 2)}
            </pre>
          )}
        </div>
      ) : null}
    </li>
  )
}

export function ArtifactsTab({ run }: { run: RunDetail }) {
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
            <ArtifactRow key={name} runId={run.run_id} name={name as ArtifactName} />
          ))}
        </ul>
      )}
    </Card>
  )
}
