import { useEffect, useRef } from 'react'

import type { PlayerAdapter } from './playerAdapter'
import styles from './VideoActivity.module.css'

/** The slice of YouTube's IFrame Player API we use. */
interface YTPlayer {
  getCurrentTime(): number
  getPlaybackRate(): number
  getPlayerState(): number
  getDuration(): number
  seekTo(seconds: number, allowSeekAhead: boolean): void
  destroy(): void
}
interface YTApi {
  Player: new (
    element: HTMLElement,
    options: {
      host?: string
      videoId: string
      width?: string
      height?: string
      playerVars?: Record<string, number | string>
      events?: { onReady?: () => void; onStateChange?: () => void; onError?: () => void }
    },
  ) => YTPlayer
}
declare global {
  interface Window {
    YT?: YTApi
    onYouTubeIframeAPIReady?: () => void
  }
}

const PLAYING = 1
let loading: Promise<YTApi> | null = null

/** Load YouTube's player script once, on first use. */
function loadApi(): Promise<YTApi> {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  loading ??= new Promise<YTApi>((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      previous?.()
      if (window.YT?.Player) resolve(window.YT)
      else reject(new Error('YouTube’s player didn’t load.'))
    }
    const script = document.createElement('script')
    script.src = 'https://www.youtube.com/iframe_api'
    script.async = true
    script.onerror = () => {
      loading = null
      reject(new Error('YouTube’s player didn’t load.'))
    }
    document.head.appendChild(script)
  })
  return loading
}

interface Props {
  videoId: string
  /** Where to start (seconds), for resuming. */
  startAt: number
  /** Called with the adapter once the player is ready, and with `null` if it goes away. */
  onAdapter: (adapter: PlayerAdapter | null) => void
  /** Pause, play, end — the moments worth reporting straight away. */
  onChange: () => void
  onFail: () => void
}

/** A YouTube video, played inside the lesson. Embedded players can't be
 * verified as closely as our own, so what is watched is tracked best-effort. */
export function YouTubeFrame({ videoId, startAt, onAdapter, onChange, onFail }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const callbacks = useRef({ onAdapter, onChange, onFail })
  useEffect(() => {
    callbacks.current = { onAdapter, onChange, onFail }
  })

  useEffect(() => {
    let player: YTPlayer | null = null
    let gone = false
    const target = document.createElement('div')
    host.current?.appendChild(target)

    loadApi()
      .then((YT) => {
        if (gone) return
        player = new YT.Player(target, {
          host: 'https://www.youtube-nocookie.com',
          videoId,
          width: '100%',
          height: '100%',
          playerVars: { playsinline: 1, rel: 0, modestbranding: 1, start: Math.floor(startAt) },
          events: {
            onReady: () => {
              if (gone || !player) return
              const p = player
              callbacks.current.onAdapter({
                position: () => p.getCurrentTime(),
                rate: () => p.getPlaybackRate(),
                playing: () => p.getPlayerState() === PLAYING,
                duration: () => {
                  const length = p.getDuration()
                  return Number.isFinite(length) && length > 0 ? length : null
                },
              })
            },
            onStateChange: () => callbacks.current.onChange(),
            onError: () => callbacks.current.onFail(),
          },
        })
      })
      .catch(() => !gone && callbacks.current.onFail())

    return () => {
      gone = true
      callbacks.current.onAdapter(null)
      try {
        player?.destroy()
      } catch {
        // the frame may already be gone
      }
      target.remove()
    }
    // The player is created once per video; resuming position is a start option.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId])

  return <div ref={host} className={styles.embed} />
}
