import { useQuery } from '@tanstack/react-query'
import { forwardRef, useImperativeHandle, useRef } from 'react'

import { audioUrl } from '../api/client'
import { keys } from '../api/queries'

export interface AudioPlayerHandle {
  seek: (seconds: number) => void
}

/**
 * The run's recording, via a short-lived signed URL (an `<audio>` element
 * cannot send the API token). When the URL expires mid-session the next range
 * request fails; the player then fetches a fresh URL and resumes from the
 * same position, so long review sessions keep working.
 */
export const AudioPlayer = forwardRef<
  AudioPlayerHandle,
  { runId: string; onTimeUpdate?: (seconds: number) => void }
>(function AudioPlayer({ runId, onTimeUpdate }, ref) {
  const audio = useRef<HTMLAudioElement>(null)
  const resumeAt = useRef<number | null>(null)
  const source = useQuery({
    queryKey: keys.runPart(runId, 'audio-url'),
    queryFn: () => audioUrl(runId),
    staleTime: Infinity, // replaced only when playback reports the URL dead
    gcTime: 0,
  })

  useImperativeHandle(ref, () => ({
    seek(seconds: number) {
      const element = audio.current
      if (!element) return
      element.currentTime = seconds
      void element.play().catch(() => {
        // Autoplay can be refused; the position is still set.
      })
    },
  }))

  if (source.isError) {
    return <p className="text-muted text-sm">Recording unavailable: {source.error.message}</p>
  }
  if (!source.data) return <div className="bg-subtle h-10 animate-pulse rounded-full" aria-hidden />

  return (
    // The transcript beside the player is the recording's text alternative,
    // so a captions <track> would only duplicate it.
    // oxlint-disable-next-line jsx-a11y/media-has-caption
    <audio
      ref={audio}
      src={source.data.url}
      controls
      preload="metadata"
      className="w-full"
      aria-label="Meeting recording"
      onTimeUpdate={(event) => onTimeUpdate?.(event.currentTarget.currentTime)}
      onLoadedMetadata={(event) => {
        if (resumeAt.current != null) {
          event.currentTarget.currentTime = resumeAt.current
          resumeAt.current = null
        }
      }}
      onError={(event) => {
        // Most likely an expired ticket: fetch a new URL once and resume in place.
        if (resumeAt.current == null) {
          resumeAt.current = event.currentTarget.currentTime
          void source.refetch()
        }
      }}
    />
  )
})
