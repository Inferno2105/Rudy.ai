import { useQueryClient } from '@tanstack/react-query'
import { FileAudio, Play, Trash2, UploadCloud } from 'lucide-react'
import { useRef, useState, type DragEvent, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { uploadAudio } from '../api/client'
import { keys, useAudioFiles, useDeleteAudio, useStartBatch } from '../api/queries'
import { PageHeader } from '../components/AppShell'
import { ConfirmDelete } from '../components/ConfirmDelete'
import { ErrorState } from '../components/states'
import { Button } from '../components/ui/button'
import { Card, CardBody, CardHeader } from '../components/ui/card'
import { Callout, LoadingBlock } from '../components/ui/feedback'
import { Field, Input } from '../components/ui/field'
import { Progress } from '../components/ui/progress'
import { useToast } from '../components/ui/toast-context'
import { formatBytes, formatDuration } from '../lib/format'
import { cn, useDocumentTitle } from '../lib/utils'

const ACCEPTED = ['.wav', '.mp3', '.m4a', '.flac']

type UploadState =
  | { kind: 'idle' }
  | { kind: 'uploading'; name: string; fraction: number }
  | { kind: 'done'; name: string; alreadyPresent: boolean }
  | { kind: 'error'; message: string }

export function NewRunPage() {
  useDocumentTitle('New run')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const files = useAudioFiles()
  const deleteAudio = useDeleteAudio()
  const notify = useToast()
  const start = useStartBatch()
  const input = useRef<HTMLInputElement>(null)
  const abort = useRef<AbortController | null>(null)

  const [selected, setSelected] = useState<string | null>(null)
  const [speakers, setSpeakers] = useState('')
  const [upload, setUpload] = useState<UploadState>({ kind: 'idle' })
  const [dragging, setDragging] = useState(false)
  const [missingRecording, setMissingRecording] = useState(false)
  const recordingStatus = useRef<HTMLParagraphElement>(null)
  const speakersInput = useRef<HTMLInputElement>(null)

  async function handleFile(file: File) {
    const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    if (!ACCEPTED.includes(extension)) {
      setUpload({
        kind: 'error',
        message: `${file.name} is not a supported recording (${ACCEPTED.join(', ')}).`,
      })
      return
    }
    abort.current = new AbortController()
    setUpload({ kind: 'uploading', name: file.name, fraction: 0 })
    try {
      const result = await uploadAudio(
        file,
        (fraction) => setUpload({ kind: 'uploading', name: file.name, fraction }),
        abort.current.signal,
      )
      setUpload({ kind: 'done', name: result.name, alreadyPresent: result.already_present })
      setSelected(result.name)
      setMissingRecording(false)
      await queryClient.invalidateQueries({ queryKey: keys.audio })
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        setUpload({ kind: 'idle' })
      } else {
        setUpload({
          kind: 'error',
          message: error instanceof Error ? error.message : 'Upload failed',
        })
      }
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files[0]
    if (file) void handleFile(file)
  }

  const speakerCount = speakers.trim() === '' ? null : Number(speakers)
  const speakersInvalid =
    speakerCount !== null &&
    (!Number.isInteger(speakerCount) || speakerCount < 1 || speakerCount > 20)

  function submit(event: FormEvent) {
    event.preventDefault()
    // The button stays enabled: an invalid submit explains itself and moves
    // focus to what needs fixing, instead of a disabled button that doesn't.
    if (!selected) {
      setMissingRecording(true)
      recordingStatus.current?.focus()
      return
    }
    if (speakersInvalid) {
      speakersInput.current?.focus()
      return
    }
    start.mutate(
      { audio: selected, num_speakers: speakerCount },
      { onSuccess: (accepted) => navigate(`/runs/${encodeURIComponent(accepted.run_id)}`) },
    )
  }

  const uploading = upload.kind === 'uploading'

  return (
    <>
      <PageHeader
        eyebrow="Process"
        title="New run"
        description="Process a recording end to end: transcription, speakers, language tagging, summary and action items."
      />

      <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Upload a recording"
              description={`${ACCEPTED.join(', ')} · kept private to your account`}
            />
            <CardBody>
              <div
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                className={cn(
                  'flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-[border-color,background-color,box-shadow,transform] duration-300',
                  dragging
                    ? 'border-accent bg-accent-soft scale-[1.01] shadow-[0_0_40px_-10px_var(--color-glow)]'
                    : 'border-strong-border hover:border-accent/50',
                )}
              >
                <div className="animate-float relative mb-4" aria-hidden>
                  <div className="bg-brand absolute inset-0 rounded-2xl opacity-40 blur-xl" />
                  <div className="bg-cta text-cta-fg relative grid size-14 place-items-center rounded-2xl">
                    <UploadCloud className="size-7" />
                  </div>
                </div>
                <p className="text-fg text-sm font-medium">Drop a recording here</p>
                <p className="text-muted mt-1 text-sm">or</p>
                <Button
                  className="mt-3"
                  onClick={() => input.current?.click()}
                  disabled={uploading}
                >
                  Choose file…
                </Button>
                <input
                  ref={input}
                  type="file"
                  accept={ACCEPTED.join(',')}
                  className="sr-only"
                  tabIndex={-1}
                  aria-label="Recording file"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) void handleFile(file)
                    event.target.value = ''
                  }}
                />
              </div>

              <div className="mt-4">
                {upload.kind === 'uploading' ? (
                  <div>
                    <div className="mb-1.5 flex items-center justify-between gap-3 text-sm">
                      <output className="text-fg truncate">Uploading {upload.name}</output>
                      <span className="text-muted tabular-nums">
                        {Math.round(upload.fraction * 100)}%
                      </span>
                    </div>
                    <Progress value={upload.fraction} label={`Uploading ${upload.name}`} />
                    <Button
                      size="sm"
                      variant="ghost"
                      className="mt-2"
                      onClick={() => abort.current?.abort()}
                    >
                      Cancel upload
                    </Button>
                  </div>
                ) : upload.kind === 'done' ? (
                  <Callout tone="info" announce="status">
                    {upload.alreadyPresent
                      ? `${upload.name} was already on the server (identical content); selected it.`
                      : `Uploaded ${upload.name} and selected it.`}
                  </Callout>
                ) : upload.kind === 'error' ? (
                  <Callout tone="danger" title="Upload failed" announce="alert">
                    {upload.message}
                  </Callout>
                ) : null}
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Or choose one of your recordings"
              description="Recordings you have uploaded. Other accounts cannot see them."
            />
            <CardBody>
              {files.isPending ? (
                <LoadingBlock label="Loading recordings" lines={3} />
              ) : files.isError ? (
                <ErrorState error={files.error} onRetry={() => void files.refetch()} />
              ) : files.data.length === 0 ? (
                <p className="text-muted text-sm">No recordings yet. Upload one above.</p>
              ) : (
                <fieldset>
                  <legend className="sr-only">Recording</legend>
                  <ul className="divide-border ring-border divide-y rounded-lg ring-1">
                    {files.data.map((file) => (
                      <li
                        key={file.name}
                        className={cn(
                          'flex items-center',
                          selected === file.name ? 'bg-accent-soft' : 'hover:bg-subtle/60',
                        )}
                      >
                        <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 py-3 pl-4 text-sm">
                          <input
                            type="radio"
                            name="recording"
                            value={file.name}
                            checked={selected === file.name}
                            onChange={() => {
                              setSelected(file.name)
                              setMissingRecording(false)
                            }}
                            className="accent-accent size-4"
                          />
                          <FileAudio className="text-muted size-4 shrink-0" aria-hidden />
                          <span className="text-fg min-w-0 flex-1 truncate font-medium">
                            {file.name}
                          </span>
                          <span className="text-muted text-xs whitespace-nowrap tabular-nums">
                            {file.duration_sec != null
                              ? `${formatDuration(file.duration_sec)} · `
                              : ''}
                            {formatBytes(file.size_bytes)}
                          </span>
                        </label>
                        <ConfirmDelete
                          title={`Delete ${file.name}?`}
                          confirmLabel="Delete recording"
                          trigger={
                            <Button
                              variant="ghost"
                              size="sm"
                              className="mx-2 shrink-0"
                              aria-label={`Delete ${file.name}`}
                            >
                              <Trash2 aria-hidden />
                            </Button>
                          }
                          onConfirm={async () => {
                            await deleteAudio.mutateAsync(file.name)
                            if (selected === file.name) setSelected(null)
                            notify({ tone: 'success', title: `Deleted ${file.name}` })
                          }}
                        >
                          <p>The recording is removed from the server. This cannot be undone.</p>
                          <p>
                            {file.meetings > 0
                              ? `${file.meetings} of your meetings ${file.meetings === 1 ? 'was' : 'were'} made from it. ${file.meetings === 1 ? 'It keeps' : 'They keep'} the transcript, summary and provenance, but can no longer play the audio.`
                              : 'No meeting has been made from it yet.'}
                          </p>
                        </ConfirmDelete>
                      </li>
                    ))}
                  </ul>
                </fieldset>
              )}
            </CardBody>
          </Card>
        </div>

        <div>
          <Card className="lg:sticky lg:top-20">
            <CardHeader title="Run options" />
            <CardBody className="space-y-5">
              <div>
                <p className="text-fg text-sm font-medium">Recording</p>
                <p
                  ref={recordingStatus}
                  tabIndex={-1}
                  className="text-muted mt-1 truncate text-sm outline-offset-2"
                >
                  {selected ?? 'None selected'}
                </p>
                {missingRecording ? (
                  <p className="text-danger mt-1 text-xs" role="alert">
                    Choose or upload a recording first.
                  </p>
                ) : null}
              </div>
              <Field
                label="Number of speakers"
                hint="Optional. Leave blank to detect automatically; if you know it, diarization is more accurate."
                error={speakersInvalid ? 'Enter a whole number from 1 to 20.' : undefined}
              >
                {({ id, describedBy }) => (
                  <Input
                    ref={speakersInput}
                    id={id}
                    aria-describedby={describedBy}
                    aria-invalid={speakersInvalid || undefined}
                    name="num_speakers"
                    autoComplete="off"
                    inputMode="numeric"
                    placeholder="e.g. 3…"
                    value={speakers}
                    onChange={(event) => setSpeakers(event.target.value)}
                  />
                )}
              </Field>
              {start.isError ? (
                <Callout tone="danger" title="Could not start the run" announce="alert">
                  {start.error.message}
                </Callout>
              ) : null}
              <Button
                type="submit"
                variant="primary"
                className="w-full"
                disabled={uploading || start.isPending}
              >
                <Play aria-hidden /> {start.isPending ? 'Starting…' : 'Start processing'}
              </Button>
              <p className="text-muted text-xs">
                Runs are processed one at a time. A long recording can take several minutes on CPU;
                you can leave this page and come back.
              </p>
            </CardBody>
          </Card>
        </div>
      </form>
    </>
  )
}
