import { useCallback, useRef, useState } from 'react'

import { Icon } from '../../../components/Icon'
import { useCourse } from '../courseContext'
import { ActivityShell } from './ActivityShell'
import { videoElementAdapter, type PlayerAdapter } from './playerAdapter'
import type { RendererProps } from './types'
import styles from './VideoActivity.module.css'
import { useWatchReporter } from './useWatchReporter'
import { YouTubeFrame } from './YouTubeFrame'

function clock(seconds: number): string {
  const whole = Math.max(Math.floor(seconds), 0)
  const m = Math.floor(whole / 60)
  const s = String(whole % 60).padStart(2, '0')
  return `${m}:${s}`
}

/** "45 sec" for a short clip, "8 min" otherwise. */
function lengthLabel(seconds: number): string {
  return seconds < 90 ? `${Math.max(Math.round(seconds), 1)} sec` : `${Math.round(seconds / 60)} min`
}

const asNumber = (v: unknown, fallback: number) => (typeof v === 'number' && v > 0 ? v : fallback)

/** A video, played right inside the lesson. Uploaded videos are streamed by
 * this site and watched under the server's eye; YouTube videos play in YouTube's
 * own player and are tracked as closely as it allows. Either way, the server —
 * not the page — decides when the video counts as watched. */
export function VideoActivity({ activity }: RendererProps) {
  const { progress, preview } = useCourse()
  const config = activity.config
  const source = config.source
  const mediaUrl = typeof config.media_url === 'string' ? config.media_url : null
  const posterUrl = typeof config.poster_url === 'string' ? config.poster_url : undefined
  const youtubeId = typeof config.youtube_id === 'string' ? config.youtube_id : null
  const driveId = typeof config.drive_id === 'string' ? config.drive_id : null
  const playable =
    (source === 'upload' && mediaUrl) || (source === 'youtube' && youtubeId) || (source === 'drive' && driveId)
  // Google gives no playback position for Drive, so the learner confirms it.
  const selfReported = source === 'drive'
  const length = typeof config.duration === 'number' ? config.duration : null
  const needed = asNumber(config.completion_threshold, 0.9)
  const maxRate = asNumber(config.max_credited_rate, 1)

  const done = progress.activities[activity.id] === 'completed'
  const watched = progress.watch[activity.id]
  const resumeAt = !done && watched && watched.position > 5 ? watched.position : 0
  const canRecord = progress.available && !preview

  const [open, setOpen] = useState(false)
  const [adapter, setAdapter] = useState<PlayerAdapter | null>(null)
  const [broken, setBroken] = useState(false)
  const [busy, setBusy] = useState(false)
  const [rate, setRate] = useState(1)
  const videoRef = useRef<HTMLVideoElement | null>(null)

  const send = useCallback(
    (body: Parameters<typeof progress.sendWatch>[1], keepalive: boolean) =>
      progress.sendWatch(activity.id, body, keepalive),
    // `progress` changes on every update; the reporter keeps the latest itself.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [activity.id, progress.sendWatch],
  )
  const { flush, tooFast, problem } = useWatchReporter({
    enabled: open && canRecord && adapter !== null && !done && !selfReported,
    adapter,
    maxRate,
    reportDuration: source === 'youtube',
    send,
  })

  // Called with the element each time the panel opens (and with null as it
  // closes). Stable, so React doesn't detach and re-attach it on every render.
  const attach = useCallback((el: HTMLVideoElement | null) => {
    videoRef.current = el
    setAdapter(el ? videoElementAdapter(el) : null)
    // Opened by a click, so starting to play is what was asked for.
    if (el) void el.play?.()?.catch?.(() => {})
  }, [])

  function onLoaded(el: HTMLVideoElement) {
    if (resumeAt && resumeAt < el.duration - 3) el.currentTime = resumeAt
  }

  function begin() {
    setBroken(false)
    setRate(1)
    setOpen(true)
    if (canRecord && !done) void progress.startActivity(activity.id)
  }

  const meta = [
    length ? `Video · ${lengthLabel(length)}` : 'Video',
    done ? 'Watched' : resumeAt ? `Resume from ${clock(resumeAt)}` : null,
    activity.is_required ? 'Required' : 'Optional',
  ]
    .filter(Boolean)
    .join(' · ')

  // Nothing real behind it yet (a draft's placeholder, an unfinished upload).
  if (!playable) {
    return (
      <ActivityShell
        icon="play"
        title={activity.title}
        meta={`Video · ${activity.is_required ? 'Required' : 'Optional'}`}
      >
        <span className={styles.soon}>Available soon</span>
      </ActivityShell>
    )
  }

  const percent = watched ? Math.round(watched.watched_fraction * 100) : 0
  let status: { text: string; tone: 'note' | 'problem' | 'plain' } | null = null
  if (broken) {
    status = { text: 'This video couldn’t be loaded. Refresh the page to try again.', tone: 'problem' }
  } else if (problem) {
    status = { text: problem, tone: 'problem' }
  } else if (preview) {
    status = { text: 'Playing in preview — your viewing isn’t recorded.', tone: 'note' }
  } else if (tooFast || rate > maxRate + 0.05) {
    status = {
      text: `Playing faster than ${maxRate}× isn’t counted toward finishing this video.`,
      tone: 'note',
    }
  } else if (done) {
    status = { text: 'You’ve watched this video.', tone: 'plain' }
  } else if (selfReported) {
    status = { text: 'Watch the video, then confirm below.', tone: 'plain' }
  } else if (percent > 0) {
    status = {
      text: `Watched ${percent}% · ${Math.round(needed * 100)}% needed`,
      tone: 'plain',
    }
  }

  async function confirm(task: () => Promise<void>) {
    setBusy(true)
    try {
      await task()
    } finally {
      setBusy(false)
    }
  }

  const player = open ? (
    <div className={styles.stage}>
      <div className={styles.frame}>
        {source === 'upload' && mediaUrl ? (
          <video
            ref={attach}
            className={styles.video}
            src={mediaUrl}
            poster={posterUrl}
            controls
            playsInline
            preload="metadata"
            controlsList="nodownload"
            aria-label={activity.title}
            onLoadedMetadata={(e) => onLoaded(e.currentTarget)}
            onPause={() => flush()}
            onEnded={() => flush()}
            onSeeked={() => flush()}
            onRateChange={(e) => setRate(e.currentTarget.playbackRate)}
            onError={() => setBroken(true)}
          />
        ) : source === 'drive' && driveId ? (
          <iframe
            className={styles.video}
            title={activity.title}
            src={`https://drive.google.com/file/d/${driveId}/preview`}
            allow="fullscreen"
            referrerPolicy="no-referrer"
            onError={() => setBroken(true)}
          />
        ) : youtubeId ? (
          <YouTubeFrame
            videoId={youtubeId}
            startAt={resumeAt}
            onAdapter={setAdapter}
            onChange={() => flush()}
            onFail={() => setBroken(true)}
          />
        ) : null}
      </div>
      <p
        className={`${styles.status} ${
          status?.tone === 'problem' ? styles.problem : status?.tone === 'note' ? styles.note : ''
        }`}
        role={status?.tone === 'problem' ? 'alert' : 'status'}
        aria-live="polite"
      >
        {status?.text}
      </p>
    </div>
  ) : null

  const toggle = (
    <button
      type="button"
      className={`btn btn-sm ${done || selfReported ? (done ? 'btn-ghost' : '') : 'btn-primary'}`}
      aria-expanded={open}
      onClick={() => (open ? setOpen(false) : begin())}
    >
      {open ? (
        'Hide video'
      ) : (
        <>
          <Icon name="play" size={14} /> {done ? 'Watch again' : resumeAt ? 'Resume' : 'Watch'}
        </>
      )}
    </button>
  )

  return (
    <ActivityShell icon="play" title={activity.title} meta={meta} done={done} panel={player}>
      {done && <span className={styles.watched}>Watched</span>}
      {toggle}
      {selfReported &&
        (done ? (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={busy || !canRecord}
            onClick={() => void confirm(() => progress.uncompleteActivity(activity.id))}
          >
            Mark as unwatched
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={busy || !canRecord}
            title={preview ? 'Progress isn’t recorded in preview' : undefined}
            onClick={() => void confirm(() => progress.completeActivity(activity.id))}
          >
            I’ve watched this
          </button>
        ))}
    </ActivityShell>
  )
}
