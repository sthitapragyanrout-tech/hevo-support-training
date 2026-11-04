import { useEffect, useRef, useState } from 'react'

import { AutosaveField } from './AutosaveField'
import { useConfigWriter } from './useConfigWriter'
import type { EditorProps } from './QuizEditor'
import styles from './VideoEditor.module.css'
import { mediaApi, type MediaAsset, type MediaLimits } from './studioApi'

type Source = 'upload' | 'youtube' | 'drive'

const YOUTUBE_HOSTS = new Set([
  'youtube.com',
  'www.youtube.com',
  'm.youtube.com',
  'music.youtube.com',
  'youtube-nocookie.com',
  'www.youtube-nocookie.com',
  'youtu.be',
])
const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/

/** The 11-character id in a YouTube link, or null. Mirrors the server's rule. */
function youtubeId(url: string): string | null {
  let parsed: URL
  try {
    parsed = new URL(url.trim())
  } catch {
    return null
  }
  const host = parsed.hostname.toLowerCase()
  if (!['http:', 'https:'].includes(parsed.protocol) || !YOUTUBE_HOSTS.has(host)) return null
  let candidate: string | null = null
  if (host === 'youtu.be') candidate = parsed.pathname.split('/')[1] ?? null
  else if (parsed.pathname === '/watch') candidate = parsed.searchParams.get('v')
  else {
    const parts = parsed.pathname.split('/').filter(Boolean)
    if (parts.length >= 2 && ['embed', 'shorts', 'live', 'v'].includes(parts[0])) candidate = parts[1]
  }
  return candidate && YOUTUBE_ID.test(candidate) ? candidate : null
}

const DRIVE_ID = /^[A-Za-z0-9_-]{10,128}$/

/** The file id in a Google Drive share link, or null. Mirrors the server's rule. */
function driveId(url: string): string | null {
  let parsed: URL
  try {
    parsed = new URL(url.trim())
  } catch {
    return null
  }
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.hostname.toLowerCase() !== 'drive.google.com') {
    return null
  }
  const parts = parsed.pathname.split('/').filter(Boolean)
  let candidate: string | null = null
  if (parts.length >= 3 && parts[0] === 'file' && parts[1] === 'd') candidate = parts[2]
  else if (['open', 'uc'].includes(parts[0])) candidate = parsed.searchParams.get('id')
  return candidate && DRIVE_ID.test(candidate) ? candidate : null
}

function clock(seconds: number): string {
  const whole = Math.max(Math.round(seconds), 0)
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

const POLL_MS = 2000

/** Where an uploaded video is, refreshed until it settles. */
function useAsset(id: number | null, onSettled?: () => void) {
  const [asset, setAsset] = useState<MediaAsset | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [seen, setSeen] = useState<number | null>(null)

  // A different video: start from scratch (state adjusted during render, not in an effect).
  if (id !== seen) {
    setSeen(id)
    setAsset(null)
    setUnavailable(false)
  }

  const settledRef = useRef(onSettled)
  useEffect(() => {
    settledRef.current = onSettled
  })

  const status = asset?.status
  useEffect(() => {
    if (id === null) return
    const before = status
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const pending = status === undefined || status === 'uploaded' || status === 'processing'
    async function load() {
      try {
        const next = await mediaApi.get(id!)
        if (stopped) return
        setAsset(next)
        if (next.status === 'uploaded' || next.status === 'processing') {
          timer = setTimeout(load, POLL_MS)
        } else if (before === 'uploaded' || before === 'processing') {
          settledRef.current?.() // it was in progress and now it isn't
        }
      } catch {
        if (!stopped) setUnavailable(true)
      }
    }
    if (pending) void load()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [id, status])

  return { asset, unavailable, set: setAsset }
}

/** Add a video to a lesson: upload one (played from this site, watching verified
 * by the server) or paste a YouTube link (played in YouTube's player, tracked as
 * closely as it allows). Everything saves as you go. */
export function VideoEditor({ activity, disabled, save, refresh }: EditorProps) {
  const config = activity.config
  const source: Source =
    config.source === 'youtube' ? 'youtube' : config.source === 'drive' ? 'drive' : 'upload'
  const assetId = typeof config.media_asset === 'number' ? config.media_asset : null
  const youtubeUrl = typeof config.youtube_url === 'string' ? config.youtube_url : ''
  const driveUrl = typeof config.drive_url === 'string' ? config.drive_url : ''
  const threshold = typeof config.completion_threshold === 'number' ? config.completion_threshold : 0.9
  const maxRate = typeof config.max_credited_rate === 'number' ? config.max_credited_rate : 1

  const write = useConfigWriter(config, (next) => save({ config: next }))
  const [problem, setProblem] = useState<string | null>(null)
  const run = (task: Promise<void>) => {
    setProblem(null)
    task.catch((err) => setProblem(err instanceof Error ? err.message : 'That didn’t save.'))
  }

  const [limits, setLimits] = useState<MediaLimits | null>(null)
  useEffect(() => {
    mediaApi.limits().then(setLimits, () => {})
  }, [])

  const {
    asset,
    unavailable,
    set: setAsset,
  } = useAsset(source === 'upload' ? assetId : null, () => void refresh?.())

  const [uploading, setUploading] = useState<{ name: string; fraction: number } | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  function problemWith(file: File): string | null {
    if (limits) {
      const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
      if (!limits.allowed_extensions.includes(extension)) {
        return `We can’t use that kind of file. Upload one of: ${limits.allowed_extensions
          .map((e) => e.toUpperCase())
          .join(', ')}.`
      }
      if (file.size > limits.max_upload_mb * 1024 * 1024) {
        return `That file is larger than the ${limits.max_upload_mb} MB limit.`
      }
    }
    return null
  }

  async function upload(file: File) {
    setUploadError(null)
    const refusal = problemWith(file)
    if (refusal) return setUploadError(refusal)
    setUploading({ name: file.name, fraction: 0 })
    try {
      const created = await mediaApi.upload(file, (fraction) =>
        setUploading({ name: file.name, fraction }),
      )
      setAsset(created)
      await write((cfg) => ({ ...cfg, source: 'upload', media_asset: created.id }))
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'The upload didn’t work. Please try again.')
    } finally {
      setUploading(null)
    }
  }

  const pick = (files: FileList | null) => {
    const file = files?.[0]
    if (file) void upload(file)
    if (input.current) input.current.value = ''
  }

  async function saveYouTube(text: string) {
    const value = text.trim()
    if (value && !youtubeId(value)) throw new Error('Paste a valid YouTube link (youtube.com or youtu.be).')
    await write((cfg) => ({ ...cfg, source: 'youtube', youtube_url: value }))
  }

  async function saveDrive(text: string) {
    const value = text.trim()
    if (value && !driveId(value)) throw new Error('Paste a valid Google Drive link (drive.google.com).')
    await write((cfg) => ({ ...cfg, source: 'drive', drive_url: value }))
  }

  async function savePercent(text: string) {
    const percent = Number(text)
    if (text.trim() === '' || Number.isNaN(percent) || percent < 50 || percent > 100) {
      throw new Error('Enter a percentage from 50 to 100.')
    }
    await write((cfg) => ({ ...cfg, completion_threshold: percent / 100 }))
  }

  async function saveRate(text: string) {
    const rate = Number(text)
    if (text.trim() === '' || Number.isNaN(rate) || rate < 0.25 || rate > 2) {
      throw new Error('Enter a speed from 0.25 to 2 (1 is normal speed).')
    }
    await write((cfg) => ({ ...cfg, max_credited_rate: rate }))
  }

  const embed = youtubeUrl ? youtubeId(youtubeUrl) : null
  const driveEmbed = driveUrl ? driveId(driveUrl) : null

  return (
    <div className={styles.editor}>
      <div className={styles.sources} role="radiogroup" aria-label="Where the video comes from">
        {(
          [
            ['upload', 'Upload a video'],
            ['youtube', 'YouTube link'],
            ['drive', 'Google Drive link'],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={source === value}
            disabled={disabled}
            className={`${styles.source} ${source === value ? styles.sourceOn : ''}`}
            onClick={() => source !== value && run(write((cfg) => ({ ...cfg, source: value })))}
          >
            {label}
          </button>
        ))}
      </div>

      {source === 'upload' && (
        <div className={styles.block}>
          {uploading ? (
            <div className={styles.status} role="status">
              <p className={styles.line}>
                Uploading <strong>{uploading.name}</strong>… {Math.round(uploading.fraction * 100)}%
              </p>
              <progress
                className={styles.bar}
                value={uploading.fraction}
                max={1}
                aria-label="Upload progress"
              />
              <p className={styles.hint}>Keep this page open until the upload finishes.</p>
            </div>
          ) : asset && (asset.status === 'uploaded' || asset.status === 'processing') ? (
            <div className={styles.status} role="status">
              <p className={styles.line}>
                <span className={styles.spinner} aria-hidden="true" />
                Processing <strong>{asset.original_name}</strong>…
              </p>
              <p className={styles.hint}>
                This can take a few minutes. You can leave this page — the video will be ready when
                you come back.
              </p>
            </div>
          ) : asset?.status === 'ready' ? (
            <div className={styles.ready}>
              <p className={styles.line}>
                Ready{asset.duration_seconds ? ` · ${clock(asset.duration_seconds)}` : ''}
                <span className={styles.name}> — {asset.original_name}</span>
              </p>
              {asset.video_url && (
                <video
                  className={styles.preview}
                  src={asset.video_url}
                  poster={asset.poster_url ?? undefined}
                  controls
                  preload="metadata"
                  playsInline
                  aria-label="Preview of the uploaded video"
                />
              )}
            </div>
          ) : asset?.status === 'failed' ? (
            <div className={styles.status} role="alert">
              <p className={styles.problem}>{asset.error || 'This video couldn’t be processed.'}</p>
              {asset.retryable && !disabled && (
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() =>
                    mediaApi.retry(asset.id).then(setAsset, (err) =>
                      setUploadError(err instanceof Error ? err.message : 'Couldn’t retry.'),
                    )
                  }
                >
                  Try again
                </button>
              )}
            </div>
          ) : assetId !== null && unavailable ? (
            <p className={styles.hint}>
              An uploaded video is attached, but you can’t see its status here.
            </p>
          ) : assetId !== null ? (
            <p className={styles.hint}>Checking the video…</p>
          ) : null}

          {!disabled && !uploading && (
            <div
              className={`${styles.drop} ${over ? styles.dropOver : ''}`}
              onDragOver={(e) => {
                e.preventDefault()
                setOver(true)
              }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setOver(false)
                pick(e.dataTransfer.files)
              }}
            >
              <input
                ref={input}
                type="file"
                className={styles.file}
                accept={limits ? limits.allowed_extensions.map((e) => `.${e}`).join(',') : 'video/*'}
                aria-label="Choose a video file"
                onChange={(e) => pick(e.target.files)}
              />
              <button type="button" className="btn btn-sm" onClick={() => input.current?.click()}>
                {assetId !== null ? 'Replace video' : 'Choose a video'}
              </button>
              <span className={styles.hint}>
                or drop a file here
                {limits &&
                  ` · ${limits.allowed_extensions.map((e) => e.toUpperCase()).join(', ')} · up to ${limits.max_upload_mb} MB and ${Math.round(limits.max_duration_minutes / 60)} hours`}
              </span>
            </div>
          )}
          {uploadError && (
            <p role="alert" className={styles.problem}>
              {uploadError}
            </p>
          )}
        </div>
      )}

      {source === 'youtube' && (
        <div className={styles.block}>
          <AutosaveField
            label="YouTube link"
            value={youtubeUrl}
            disabled={disabled}
            onSave={saveYouTube}
            placeholder="https://www.youtube.com/watch?v=…"
            hint="Plays inside the lesson. Watching is tracked as closely as YouTube’s player allows."
          />
          {embed && (
            <div className={styles.embed}>
              <iframe
                title="Preview of the YouTube video"
                src={`https://www.youtube-nocookie.com/embed/${embed}`}
                allow="encrypted-media; picture-in-picture"
                referrerPolicy="strict-origin-when-cross-origin"
                loading="lazy"
              />
            </div>
          )}
        </div>
      )}

      {source === 'drive' && (
        <div className={styles.block}>
          <AutosaveField
            label="Google Drive link"
            value={driveUrl}
            disabled={disabled}
            onSave={saveDrive}
            placeholder="https://drive.google.com/file/d/…/view"
            hint="Plays inside the lesson. Set the file’s sharing to “Anyone with the link”, or learners will be asked to request access."
          />
          {driveEmbed && (
            <div className={styles.embed}>
              <iframe
                title="Preview of the Google Drive video"
                src={`https://drive.google.com/file/d/${driveEmbed}/preview`}
                allow="fullscreen"
                referrerPolicy="no-referrer"
                loading="lazy"
              />
            </div>
          )}
          <p className={styles.hint}>
            Google doesn’t share how much of a Drive video was watched, so learners confirm it
            themselves (“I’ve watched this”). Trainers see it marked as self-reported. For watching
            that’s checked, upload the video instead.
          </p>
        </div>
      )}

      {source !== 'drive' && (
      <div className={styles.tracking}>
        <h5 className={styles.heading}>How watching is counted</h5>
        <div className={styles.fields}>
          <div className={styles.number}>
            <AutosaveField
              label="Share that must be watched (%)"
              type="number"
              value={String(Math.round(threshold * 100))}
              disabled={disabled}
              onSave={savePercent}
              hint="Skipping ahead doesn’t count; learners must really watch this much."
            />
          </div>
          <div className={styles.number}>
            <AutosaveField
              label="Fastest speed that counts"
              type="number"
              value={String(maxRate)}
              disabled={disabled}
              onSave={saveRate}
              hint="1 is normal speed. Watching faster than this isn’t credited."
            />
          </div>
        </div>
      </div>
      )}

      {problem && (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      )}
    </div>
  )
}
