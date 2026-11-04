# Videos: upload, processing, playing, and verified watching

How a video gets from an author's computer to a learner's lesson, and how we decide it was
watched. Code: `backend/apps/media_pipeline/` (files and processing),
`backend/apps/progress/watch.py` + `watching.py` (verified watching),
`backend/apps/activities/video.py` (the activity), `frontend/src/features/catalog/activities/`
(player and tracker) and `frontend/src/features/studio/VideoEditor.tsx`.

## The path of an upload

1. **Upload** (`POST /api/v1/authoring/media/`, authors only). Checked before anything is
   stored: extension allow-list, declared size (413 before the body is read), the real byte count
   *while* it streams to disk, free disk space (`MEDIA_MIN_FREE_MB` must remain), at most
   `MEDIA_MAX_UNFINISHED_PER_USER` unfinished uploads, then **ffprobe** proves it is a decodable
   video within limits (length 1 s…`MEDIA_MAX_DURATION_SECONDS`, ≤ `MEDIA_MAX_PIXELS`). A refused
   upload leaves nothing on disk. Files are stored under UUID names, never the uploader's.
2. **Process** (a Celery task on the `media` queue). The task *claims* the asset with one
   conditional UPDATE, converts into a private temp folder (H.264/AAC MP4, ≤ 1280 px wide,
   `faststart`, first video + first audio stream only, output size capped), then **verifies the
   output**: it exists, is H.264, no wider than 1280, within 2 % of the source's length, and
   decodes end to end without error. Only then are the video and poster moved into place
   (atomic renames) and `ready` committed.
3. **Delete the original** — only after `ready` is committed, only inside `originals/`, never
   when `MEDIA_KEEP_ORIGINALS` is true. If deletion fails the asset stays `ready` and the sweeper
   retries. Any earlier failure keeps the original.
4. **Play.** `GET /api/v1/media/<id>/video/` (and `/poster/`) with HTTP Range support. Authorised
   on **every** request (see below). `MEDIA_ACCEL_REDIRECT` lets nginx send the bytes after we
   have authorised (`X-Accel-Redirect`).

## Who can play what

| Who | Can play |
|---|---|
| anyone not signed in | nothing (403) |
| an author | videos they uploaded, and videos used by any draft / in-review course |
| an administrator | any ready video |
| everyone else | a **ready** video used by a **published, un-archived** course, **and** only if its lesson is open to them (in a course that goes in order, a locked lesson answers **409**, exactly like the progress API) |
| anything else | 404 (the same answer as "doesn't exist") |

`MEDIA_ROOT` is not mapped to any URL; stored paths are only used after resolving inside their
folder. Archiving or unpublishing cuts streaming off at the next request. An author can attach
only an upload they own (or any, if an administrator).

## Verified watching

The browser sends a heartbeat every 15 s (and on pause/seek/hide/leaving the page) listing which
stretches it played. The server believes only as much as **its own clock** allows:

* the player says **hello** (an empty heartbeat) the moment playback starts, so the server's
  clock runs from then;
* credit comes from a bucket per learner and activity, filled at the credited speed (+10 %),
  starting with just 5 s and holding at most 90 s — so a quiet client can't bank hours, and
  several tabs share one budget;
* only *new* coverage counts: skipped sections earn nothing, rewatching earns nothing;
* a heartbeat reporting a speed above the credited maximum earns nothing;
* malformed claims (out of order, overlapping, past the end, non-finite, too many…) are refused
  outright and change nothing; `(session, seq)` makes retries idempotent and ignores replays;
* each heartbeat runs under a row lock, so racing requests can't lose or double-count updates;
* the **server** marks the activity complete at `credited ≥ threshold × duration`; the client
  never says "done", and the generic "mark complete" endpoints refuse video activities.

Guaranteed, and tested for every input: *credited seconds ≤ 5 + real seconds × credited
speed × 1.1*, and credited ranges ⊆ claimed ranges ⊆ the video. So finishing a video takes at
least about (share needed × length − 5 s) ÷ 1.1 of real time — for a 30-second video, ~20 s.
(A first version allowed 20 s up front; trying it in a browser showed a single forged request
could then finish a 30-second clip, so the allowance is small and the player announces start.)

**What this cannot do:** prove a person was watching. A muted tab left playing earns credit like
anyone's. Unusual patterns (credit refused, parallel sessions, mostly background playback,
too-fast playback; always, for YouTube) set `needs_review` — shown to trainers as "Worth a
look" with a plain reason — and never block the learner.

**Google Drive** plays in Drive's embedded preview and is the one source with no verification at
all: Google exposes no position, so the learner confirms it and the console says "Confirmed by the
learner". Watch heartbeats are refused for it. Only `drive.google.com` file links are accepted
(`/file/d/<id>/…`, `open?id=`, `uc?id=`); folders and other hosts are refused.

YouTube plays in YouTube's own player and is tracked from polled positions. Its length is what
the browser reports (held fixed once set), so it is best-effort by nature.

## Running it

| | |
|---|---|
| Local | `brew install ffmpeg`, then `make dev-worker` next to `make dev`. Uses Celery's **filesystem broker** in `backend/.celery-broker/` — no Redis or Docker needed. |
| Docker/production | `docker compose up` starts a `worker` service (ffmpeg is in the image) with Redis as the broker and a shared `media` volume. |
| Tests | tasks run inline (eager); `tests/test_media_worker.py` starts a **real worker process** (Postgres + ffmpeg required, else skipped with a reason). |

Settings (env vars): `MEDIA_ROOT`, `MEDIA_MAX_UPLOAD_MB` (1024), `MEDIA_MAX_DURATION_SECONDS`
(7200), `MEDIA_MAX_PIXELS`, `MEDIA_MAX_OUTPUT_MB`, `MEDIA_MIN_FREE_MB`, `MEDIA_KEEP_ORIGINALS`,
`MEDIA_MAX_ATTEMPTS` (3), `MEDIA_MAX_UNFINISHED_PER_USER` (3), `MEDIA_WORKER_CONCURRENCY` (1,
never more than 2), `MEDIA_TRANSCODE_TIMEOUT_SECONDS`, `CELERY_BROKER_URL`, `MEDIA_ACCEL_REDIRECT`.

### Recovery (the database is the source of truth)

The filesystem broker is for development: Kombu documents it as such, and it has **no redelivery
after a hard kill**. So nothing relies on the broker being reliable. Each asset records its state,
attempts and a lease; a sweeper (`process_media --recover`, run when a worker starts and every
5 minutes by Celery beat) re-queues anything waiting with no message in flight (lost message,
broker down at upload), releases a dead worker's lease, fails what keeps failing with a plain
sentence, removes stale temp folders and half-written uploads, and finishes deferred deletions.
Duplicate messages are harmless: only one worker can claim an asset.

Failures are classified. *Transient* (disk full, timeout, a killed encoder, a failed output
check): back to the queue with a delay, up to `MEDIA_MAX_ATTEMPTS`, then failed with a
retryable message — the author can press **Try again** once the cause is fixed. *Permanent*
(not a video, over a limit, original gone): failed at once. The Studio only ever shows a sentence;
ffmpeg's own output goes to the log.

## Known limits

* One server and one worker are assumed; the throttle on heartbeats uses Django's default cache,
  which is per process (use a shared cache in a multi-process deployment).
* Anyone who can play a video can in principle save it (it is a plain MP4 served to them); we only
  control *who* may fetch it.
* ffmpeg runs under `nice` (`MEDIA_FFMPEG_NICE`, default 10) and the final decode check is capped at 2 threads. Without this, two conversions finishing together took every core for a couple of seconds and stalled the whole site (found by the load test, `docs/simbot.md`). The cost: a conversion is slower while the machine is busy.
* The filesystem broker shouldn't be used in production; ffmpeg memory isn't capped on macOS;
  there is no per-user storage quota, no orphaned-upload cleanup for assets that were never
  attached to a course, no captions, no HLS/adaptive bitrate, no resumable chunked uploads.
