import { RotateCcw } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { useResume } from '../../api/queries'
import type { RunDetail } from '../../api/types'
import { BATCH_STAGE_ORDER, stageLabel } from '../../lib/stages'
import { Button } from '../../components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogTrigger } from '../../components/ui/dialog'
import { Callout } from '../../components/ui/feedback'
import { Field, Select, Switch } from '../../components/ui/field'

/**
 * Resume a batch run (finish stages that failed or never ran), or re-run it
 * from a chosen stage. The server refuses a resume that would mix
 * configurations in one run; that refusal is shown verbatim because it names
 * exactly which setting changed.
 */
export function ResumeDialog({ run }: { run: RunDetail }) {
  const [open, setOpen] = useState(false)
  const [forceStage, setForceStage] = useState('')
  const [allowMixed, setAllowMixed] = useState(false)
  const resume = useResume(run.run_id)

  const incomplete = run.status !== 'completed'

  function submit(event: FormEvent) {
    event.preventDefault()
    resume.mutate(
      { force_stage: forceStage || null, allow_mixed_config: allowMixed },
      { onSuccess: () => setOpen(false) },
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) resume.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button variant={incomplete ? 'primary' : 'secondary'}>
          <RotateCcw aria-hidden /> {incomplete ? 'Resume' : 'Re-run'}
        </Button>
      </DialogTrigger>
      <DialogContent
        title={incomplete ? 'Resume this run' : 'Re-run stages'}
        description={
          incomplete
            ? 'Runs every stage that has not completed. Completed stages are kept.'
            : 'Choose a stage to re-run it and every stage after it. Their current outputs are deleted.'
        }
      >
        <form onSubmit={submit} className="space-y-5">
          <Field
            label="Re-run from stage"
            hint={
              forceStage
                ? `${stageLabel(forceStage)} and every later stage will be deleted and run again.`
                : 'Leave empty to only run what is missing.'
            }
          >
            {({ id, describedBy }) => (
              <Select
                id={id}
                aria-describedby={describedBy}
                value={forceStage}
                onChange={(event) => setForceStage(event.target.value)}
              >
                <option value="">Only missing stages</option>
                {BATCH_STAGE_ORDER.map((name) => (
                  <option key={name} value={name}>
                    {stageLabel(name)}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <Switch
            checked={allowMixed}
            onCheckedChange={setAllowMixed}
            label="Allow a changed configuration"
            description="For debugging only. The run is then marked inconsistent and excluded from evaluation."
          />

          {resume.isError ? (
            <Callout tone="danger" title="The server refused" announce="alert">
              {resume.error.message}
            </Callout>
          ) : null}

          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="ghost">Cancel</Button>
            </DialogClose>
            <Button
              type="submit"
              variant={forceStage ? 'danger' : 'primary'}
              disabled={resume.isPending || (!incomplete && !forceStage)}
            >
              {resume.isPending ? 'Starting…' : forceStage ? 'Delete and re-run' : 'Resume'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
