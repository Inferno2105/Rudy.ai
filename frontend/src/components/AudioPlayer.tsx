import { forwardRef, useImperativeHandle, useRef } from 'react'

import { audioUrl } from '../api/client'

export interface AudioPlayerHandle {
  seek: (seconds: number) => void
}

/**
 * The run's recording. The server supports HTTP Range requests, so the native
 * controls and `seek()` (click a transcript timestamp) can jump anywhere.
 */
export const AudioPlayer = forwardRef<
  AudioPlayerHandle,
  { runId: string; onTimeUpdate?: (seconds: number) => void }
>(function AudioPlayer({ runId, onTimeUpdate }, ref) {
  const audio = useRef<HTMLAudioElement>(null)

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

  return (
    // The transcript beside the player is the recording's text alternative,
    // so a captions <track> would only duplicate it.
    // oxlint-disable-next-line jsx-a11y/media-has-caption
    <audio
      ref={audio}
      src={audioUrl(runId)}
      controls
      preload="metadata"
      className="w-full"
      aria-label="Meeting recording"
      onTimeUpdate={(event) => onTimeUpdate?.(event.currentTarget.currentTime)}
    />
  )
})
