# Practice tickets (simbot): an AI customer, scored on six things

An intern answers a customer ticket in a window inside the platform, an AI plays the customer,
and the conversation is scored. It is **practice, not a test**: finishing enough scored tickets
(five by default) completes the activity and opens the next lesson, whatever each one scored. A
question can be skipped. Code: `backend/simbot_engine/` (the engine — no Django), `backend/apps/bot_sim/`
(storage, queues, API), `backend/apps/activities/bot_sim.py` (the activity),
`frontend/src/features/catalog/activities/` (`SimActivity`, `TicketWindow`, `SimResults`) and
`frontend/src/features/{studio/BotSimEditor,admin/PracticeScenariosPage,admin/SimTranscriptPage}.tsx`.

It is a port of the standalone Zendesk-based bot (personas, topic pool, customer prompt, five
model-judged dimensions plus a deterministic turnaround score, same weights). Zendesk is used
**read-only, as a source of past customer questions** (see "Past customer queries"); nothing is ever
created in Zendesk and learners never practise there. Not ported: the polling thread, the CSV, the
CLI. The conversation is **ticket-style** (a thread you reply to and come back to), not live chat.

## How a ticket runs

1. **Start** (`POST /api/v1/sim/activities/<id>/sessions/`). Same rules as any activity (published,
   lesson open, tickets left, not already completed), plus: an **approved** scenario they haven't
   had must exist (see below). One open ticket per learner and activity — starting again resumes it.
2. The customer's **opening message** is on screen immediately; no model call is made at start.
3. **Reply** (`POST …/sessions/<id>/messages/`, ≤ 4000 characters, idempotent on `client_id`). The
   reply is stored and stamped *by the server*, then a worker scores it and writes the customer's
   answer. The window shows "Customer is replying…" and polls every ~2 s. Closing the window loses
   nothing; the ticket is still there on return.
4. The customer decides how it ends (`follow_up`, `escalate`, `satisfied`, `close`), or the
   activity's reply limit (3–6, default 6) is reached, or the learner presses **Finish**. Silence
   is handled like the original bot: a nudge after ~10 min (an "I'll be back in 5 minutes" is
   honoured), a close after the session cap (90 min). These rules are applied when someone looks at
   the ticket *and* by a sweeper, so a learner who has walked away still gets a result.
5. **Finalize**: once every reply is scored, one transaction writes the result, one
   `ActivityAttempt`, the `ActivityProgress` transition and `state = finished`.
6. Fewer than **2 scored replies** → the ticket is *abandoned*: no attempt, no score (the original
   bot saved such sessions as 0.0).

### Finishing the activity, and skipping

* **Completion** = finish **N scored tickets** (`required_tickets`, 1–20, default **5**). A ticket is
  *scored* when it has ≥ 2 replies and finishes. Passing each ticket is **not** required; a ticket's
  "Above / Below the pass mark" is feedback. An optional Studio switch, *Also require the average of
  the last N to reach the pass mark* (`require_average`, default **off**), adds that condition; with
  it, a learner who falls short keeps practising and only their most recent N count. The decision
  is made inside the same locked transaction that records the attempt, so two quick finishes can't
  both complete or double-count it.
* **Most tickets allowed** (`max_attempts`, 0 = no limit, the default) caps the tickets a learner
  may take; Studio refuses a cap below N. Using the cap without finishing N ends the activity as
  *exhausted* (the lesson stops blocking, as with a quiz).
* **Skip** (`POST …/sessions/<id>/skip/`, a reason: *duplicate / unclear / not relevant*): only
  before the learner has replied, never in a preview, at most **5 per learner per activity**
  (`SIMBOT_SKIPS_PER_ACTIVITY`). A skipped ticket is not a ticket: no attempt, no score, no quota,
  and not counted toward the day's limit; the question is never served to that learner again.
  Repeating the call changes nothing.
* **Which question next:** one they haven't had, preferring a different topic from their last
  two; never a skipped one; a repeat (marked *repeated* for trainers) only if the bank holds fewer
  questions than they need. If nothing new is left they are told so plainly.
* **A question skipped for the same reason by three different learners** goes back to draft with a
  note ("Skipped as unclear by 3 learners.") for a trainer to look at.

## The scoring contract

One function builds the result (`simbot_engine/outcome.py`); the API, the stored result and the
attempt all read it, so they can't disagree.

* Per reply: communication, empathy, accuracy, concreteness as integers 1–5 (clamped), plus
  **turnaround** 1–5 from server timestamps (≤ 5 min → 5, ≤ 10 → 4, ≤ 15 → 3, ≤ 30 → 2, else 1).
* **Docs referenced** (1–5 → part of the same weighted sum): a deterministic part (no link anywhere
  → 1, a link off the docs site → 2, a `docs.hevodata.com` link → 3) plus a model-judged
  relevance part (0–2). It checks *that and how the reply points to the docs*; it does **not**
  open the page.
* Per ticket: each dimension is the mean of its replies; **overall = weighted mean on the 1–5
  scale** (weights communication .15, empathy .15, accuracy .25, docs .15, concreteness .20,
  turnaround .10), rounded **once**, half-up, to 2 decimals. Everything else derives from that
  rounded number.
* **Scaled = raw ÷ 5.** The lowest possible score is 1.0 (0.20 scaled), so this is not a 0–100 %
  scale — screens show **"3.84 / 5"**, never a percentage.
* **Pass mark** is stored on the activity as 0–1 (default **0.7 ≙ 3.50 / 5**, allowed 0.4–1.0);
  Studio edits it "out of 5". `passed ⇔ overall ≥ pass mark`, compared in integer hundredths (3.495
  rounds to 3.50 and passes; 3.494 doesn't). For practice tickets this marks one ticket "above" or
  "below" the pass mark; it does not decide completion (see above).
* `ActivityAttempt.score` is the **scaled** value and `passed` the same boolean; the full result
  (metrics with notes, narrative, flags) stays on the ticket.
* **Turnaround** = customer message *delivered* → the learner's reply *accepted by the API*, both
  server clocks. A customer message is "delivered" when it was committed, so our own outages and
  model latency never count against the learner. Time with the window closed counts (inbox
  semantics).

### What the scores do and don't mean

Every metric except turnaround is a model's opinion. Each metric carries a `basis`
(`deterministic`, `link_check+model_relevance`, `model_judgment`; `grounded` is reserved), the
learner and trainer screens say "AI-assessed" where it applies, and `result.grounded` is `false`
until a scenario carries a `reference_answer` and the scorer is given it (the schema is ready;
grounding is a follow-up). **Accuracy is not verified correctness.** Scores vary from run to run;
treat a pass as evidence, not proof. Replies are passed to the scorer as delimited data with an
instruction to ignore anything inside them; output is validated and clamped; obvious gaming
(copying the customer, pasting walls of text, a perfect score on a two-reply ticket) is capped or
flagged **needs review** for trainers (never shown to learners).

## Scenarios: nothing unapproved reaches a learner

A learner only ever gets an **approved** scenario matching the activity's customer type and topics.
If there is none, `start` answers 409 "Practice isn't available yet — your trainer needs to approve
practice scenarios." and nothing is created or called. A ticket keeps a **snapshot** of its scenario,
so later edits never alter a recorded transcript. Scenarios come from three places:

| Source | How it becomes approved |
|---|---|
| **Past customer queries** (Zendesk, read-only) | **Automatically**, only if every strict check passes; otherwise a draft (or dropped). See below. |
| **AI-written** ("Generate drafts") | A trainer approves it. |
| **Written by hand** | A trainer approves it. |

* **Studio**: the practice-ticket editor shows how many approved scenarios match. Publishing is
  **blocked** when that is fewer than the tickets to finish (a learner could never complete it) and
  **warns** when it is fewer than that plus the skips allowed (someone who skips a lot could run
  out). **Preview** lets an author play any scenario, including drafts, scored nowhere.
* **Console → Practice scenarios** (`/admin/practice`, `catalog.author_content`): filter (status,
  topic, customer type, **source**, **needs attention**, or one import's questions), read in full,
  edit, **Approve / Reject / Retire / Restore** (editing an approved scenario sends it back to
  draft), write one by hand, or **Generate drafts**. Each question shows where it came from, whether
  it was approved automatically, and how it is doing in practice: tickets finished, average score,
  and how often learners skipped it and why. Every change is audited.
* `manage.py seed_scenarios` creates approved *sample* scenarios for development; nothing
  approves itself in production *except* imports that pass the strict checks. `manage.py
  generate_scenarios --count N [--topic …] [--persona …] [--from-file …]` makes drafts from the
  command line. Free text from outside is passed through the PII scrubber first.

## Past customer queries (Zendesk, read-only)

Practice questions can be written from real, closed Zendesk tickets, so interns practise on what
customers actually ask. **Nothing is ever created or changed in Zendesk** (the reader's transport has
a `get` and nothing else; a test asserts it), and learners never leave the platform.

**What is read.** A random sample of *closed* tickets in the ticket forms named "Query" / "Query_Old"
(`ZENDESK_FORM_NAMES`), then each ticket's first message. **Only a customer's own words are used.**
A ticket is accepted only if **all** of these hold, and anything missing or unknown is rejected:

* the first comment is **public** (not an internal note) and is the ticket's **first** comment;
* its author is the ticket's **requester**, and that user's role is **end-user** (not an agent or admin);
* the ticket was **typed by a customer**: not created through the API, by a rule, the system or an
  import (the original bot created its own practice tickets through the API — those must never come
  back as "customers"), and was **opened by the requester themselves**, not by an agent on their behalf;
* the requester, group and tags are not on the exclusion lists (`ZENDESK_EXCLUDE_REQUESTER_IDS`,
  `…_GROUP_IDS`, `…_TAGS` — set these to the old bot's account, group and tags);
* an email from a staff domain (`ZENDESK_STAFF_DOMAINS`) is rejected; the message is not empty; any
  quoted earlier thread is cut off and the text is limited to 500 characters.

`manage.py audit_zendesk_sample --count N` applies these rules to a sample and prints how many pass
and why the rest don't, with ticket ids so a person can open a few in Zendesk and check. It reads
Zendesk only: nothing goes to the model and no message text is kept. **An import is refused until
an audit has been run.**

**What happens to an accepted message.** It is scrubbed of emails, phone numbers, IP addresses,
long ids and link query strings, then the model decides whether it can be a practice question
(answerable from the public documentation, one question, English, no account investigation) and
rewrites it without any personal detail. The rewrite is checked again (personal data that survived,
foreign links, a name left in, length, keywords, confidence). The outcome is one of:

| Outcome | When |
|---|---|
| **Approved automatically** | every check passes, confidence ≥ 0.8, a single question, and automatic approval is on |
| **Draft** for a trainer | only a judgment call is in doubt (confidence 0.6–0.8, several questions), or automatic approval is off |
| **Dropped** (counted, never stored) | not usable, personal data left, a link off the docs site, a name, wrong length, no keywords, not English, confidence < 0.6, a different topic from the one asked for |

A near-duplicate of **anything** already in the bank (including retired questions) is not saved, and
a ticket already imported can never be imported twice (a unique ticket id guards it, even if two
imports race).

**Controls.**
* **Console → Practice scenarios → Past customer queries**: *Import from Zendesk* (an administrator;
  1–50 questions, optionally one topic; runs on the practice worker, one at a time), progress, and a
  plain-language result per import (examined, approved, for review, duplicates, and each reason
  something wasn't used). *Show these questions* filters to one import.
* **Automatic approval** can be switched off in the Console (administrators; audited) and by
  `SIMBOT_AUTO_APPROVE=false`, which overrides the Console. Off → every import lands as a draft.
* **Undo**: *Send N back to draft* returns everything an import approved automatically (anything a
  person approved is left alone). Individual questions can be retired at any time.
* `manage.py import_zendesk_scenarios`, `manage.py purge_zendesk_ids` (forgets which ticket each
  scenario came from; the questions stay).

### Keeping the bank stocked: the warning and the nightly top-up

A learner who starts practice when no scenario is approved just sees "Practice isn't available yet —
your trainer needs to approve practice scenarios." Nothing is imported on a learner's click: an import
takes minutes, sends text to a third party, and is admin-only by design.

* **The warning.** Console → Practice scenarios shows a banner when the bank is **empty** ("learners
  can't start practice", with *Review drafts* if any are waiting, *Import now* for an administrator
  when the gate is open, otherwise the reason importing is off) and a softer one when it is **low**
  (fewer approved than `SIMBOT_BANK_TARGET`, default 30).
* **The nightly top-up** (`bot_sim.top_up`, Celery beat, 02:30 UTC; `SIMBOT_TOPUP_HOUR/MINUTE`) queues
  one ordinary import of `SIMBOT_TOPUP_COUNT` tickets (default 20, never more than the 50 cap). It is
  **off until an administrator switches it on** (Console, audited), and `SIMBOT_TOPUP_ENABLED=false`
  overrides the Console. Because it is the same import, every safeguard above applies unchanged: the
  same gate (sign-off, audit, configured Zendesk and model), scrubbing, strict approval, duplicate
  checks, the daily token cap, and *Send back to draft*. It does nothing — and records why, shown in
  the Console — when the switch is off, the gate is closed, the bank already has enough approved
  questions, `SIMBOT_TOPUP_MAX_DRAFTS` (25) drafts are waiting for review (otherwise it would only pile
  up drafts), an import is already running, or it is **paused**: the last `SIMBOT_TOPUP_PAUSE_AFTER` (3)
  nights added nothing. An administrator running an import by hand, or switching the top-up off and on,
  lifts a pause.
* Nightly runs appear in the import history as "nightly top-up" (no person started them) and can be
  reverted like any other. Skipped nights are not runs: only the latest check is kept
  (`PracticeSettings.topup_last_check`).
* It needs the `beat` process (`make dev-beat`, the `beat` service in Compose) and the practice
  worker. If beat isn't running, nothing tops up, and nothing says so.

### Data flow and the sign-off that must be recorded first

| Step | Where the customer's text goes |
|---|---|
| Read | Zendesk → the practice worker's memory, over HTTPS, with a read-only API token held in the environment |
| Scrub | in memory; emails, phones, IPs, ids and link parameters replaced |
| Model | the scrubbed text (**≤ 500 characters per ticket**, with its subject) is sent to the model provider |
| Stored | only the **rewritten, anonymised question**, the Zendesk ticket id, and counts. **The customer's own wording is never stored** (a test checks the scenario, import, model-call and settings tables for it). The audit keeps ticket ids and counts, no text |
| Shown | learners see only the rewritten question; the ticket id, source, and review state are trainer-only |

**Importing is off until all of this is true:** `SIMBOT_ZENDESK_IMPORT_ENABLED=true`, **and**
`SIMBOT_ZENDESK_SIGNOFF` holds a sentence recording who approved it, when, and the reference; Zendesk
credentials are set; the model is configured; and an audit has been run. Each missing piece is
named in the Console and in the API's refusal, and refusals are audit-logged. The code can insist
that a sign-off is *recorded*; it cannot grant one.

Sign-off checklist (for whoever approves the data transfer):
- [ ] The provider's terms for the model API are acceptable for customer text (retention, training use, region).
- [ ] The Zendesk API token is read-only and scoped to what's needed; its owner and rotation are known.
- [ ] The ≤ 500-character scrubbed excerpt is acceptable to send; a sample audit (`audit_zendesk_sample`) has been checked against Zendesk by a person.
- [ ] The exclusion lists name the old bot's account, group and tags.
- [ ] Who may start an import (administrators) and who may review results (trainers) is agreed.
- [ ] Retention is agreed (`purge_zendesk_ids`; transcripts per `purge_transcripts`), and how to switch it all off (`SIMBOT_ZENDESK_IMPORT_ENABLED=false`) is known.
- [ ] The reference is written into `SIMBOT_ZENDESK_SIGNOFF`.

## Running it: separate processes, bounded model use

The web process **never calls the model**. Work runs in its own worker processes:

| Process | Command | Job |
|---|---|---|
| `worker-media` | `make dev-worker-media` | ffmpeg conversions (1–2 at a time) |
| `worker-sim` | `make dev-worker-sim` | scoring, customer replies, finalizing (`SIMBOT_WORKER_CONCURRENCY`, default 4, max 8) |
| `beat` | `make dev-beat` | the one scheduler: recovery sweepers |

`make dev-workers` starts all three; Compose has the same three services. A hung model call can't
stall a conversion and vice versa — they don't share a process.

Settings (all `SIMBOT_*`, see `config/settings/base.py`): `LLM` (`openai`; `fake` only outside
production — prod refuses to start with it), `MODEL`, `EVAL_MODEL`, `MAX_EXCHANGES`,
`SESSION_CAP_MINUTES`, `LLM_RPM`/`LLM_TPM` (provider limits, enforced across all workers by one
locked database row), `LLM_CALL_TIMEOUT` (30 s), `LLM_CALL_ATTEMPTS` (3, jittered backoff,
honours `Retry-After`), `SESSION_TOKEN_BUDGET`, `DAILY_TOKEN_CAP`, `DAILY_SESSIONS_PER_USER`,
breaker (`BREAKER_FAILURES`/`BREAKER_COOLDOWN_SECONDS`), `TRANSCRIPT_RETENTION_DAYS`. The API
throttles start/reply/poll per user (10 / 20 / 120 per minute). The model key is `OPENAI_API_KEY`
in the environment only.

When the breaker is open or a cap is reached, *new* tickets get a plain "Practice is paused";
tickets already open keep their state and resume. Every model call is recorded (`LLMCall`: task,
model, tokens, latency, status) for cost and audit. `manage.py purge_transcripts` removes
transcript text older than the retention period, keeping scores.

## Never twice: idempotency and recovery

The database is the source of truth; queues only carry hints.

* Unique keys are the commit points: `(session, seq)` and `(session, client_id)`. The customer's
  answer to reply *n* is the row `seq = n+1`, so a second worker cannot create a second answer, and
  a repeated POST returns the existing reply.
* A reply is claimed with a **lease** (compare-and-set). *Score* (written once with
  `UPDATE … WHERE scores IS NULL`) and *answer* are independent steps, so a retry after "scored,
  not answered" does only the answer. A model call whose result was lost is simply asked again
  (bounded, logged), never double-committed.
* Finalize is one transaction under its own lease with `OneToOne(attempt)`; it waits for every
  reply to be scored and never produces a partial score. The narrative is written once.
* The sweeper (beat, every minute, and when a worker starts) requeues expired leases, resumes
  tickets with pending work, applies idle rules and closes abandoned ones.
* Tested with injected faults at each step, duplicate deliveries, two workers racing for one
  reply, and a **real worker process killed with SIGKILL mid-turn** (`tests/test_sim_worker.py`,
  needs Postgres). A mutation check confirmed these tests fail when the guards are removed.

### When a worker keeps dying

A killed worker never reports a failure, so a job that *kills* its worker used to be retried for
ever and the learner stayed on "Finishing this ticket…" (and, with one live ticket per learner and
activity, could not start another). Both retries are now counted at the moment the job is taken:

* A reply's job taken `SIMBOT_MAX_JOB_ATTEMPTS` times without finishing is given up like any other
  failure: the learner sees "The customer couldn't reply just now" and can press Try again. Waiting
  for the rate gate refunds the attempt, so only real tries count.
* A ticket whose result job has been taken `SIMBOT_MAX_FINALIZE_CLAIMS` (12) times without finishing
  is closed as `feedback_failed`. It does not count as an attempt and the learner can start again.
  (With the 2-minute lease this is about half an hour of trying.)
* After a minute of "Finishing…" the screen says it is taking longer than usual.

**macOS development only:** a forked Celery worker that is the first to use Apple's certificate store
(the model client does, through `truststore`) can be killed by the Objective-C runtime, which shows
as "Python quit unexpectedly" (crash report: `crashed on child side of fork pre-exec`,
`performForkChildInitialize`). The `Makefile` exports `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` for
the dev workers, the standard remedy; restart `make dev-workers` for it to apply. If it ever
persists, `celery … -P threads` avoids forking entirely (no time limits or recycling in that mode).
Linux (CI, Docker, production) has no such runtime.

## Load test (13 tickets at once, with videos converting)

`tests/load/` starts real processes on Postgres — **gunicorn** (3 workers × 4 threads, as the image
now ships; `LOAD_WEB=runserver` uses Django's dev server instead), two media workers, four practice
workers, beat — and plays **13 tickets at once** (up to 6 replies each, 1–3 s think time, polling every
2 s like the browser) while **three 109 MB, 60 s, 1280×720 videos upload and convert**. The model is the
scripted fake: its latency (0.3–1.5 s), 429s (5 %) and timeouts (1 %) are **synthetic** — the queueing,
locks, rate gate, ffmpeg and HTTP are real. Run it with `make load-test`. Criteria were written before
the first run (a first shakedown with a trivial 1 MB clip and 3-reply tickets passed everything; the
figures below are from the heavier workload that replaced it). Measured on one 8-CPU laptop, so these
are not capacity claims for a server.

**What held in every run, on every web server:** all 13 tickets finished; one scoring call and one
answer per reply, contiguous sequence numbers, one attempt per finished ticket, no failed turns. A
tight limit (90 model calls/min for ~170 calls) engaged the shared gate without losing or duplicating
anything; the worst send → reply there was 43 s (a fixed one-minute window can make a turn wait most of
a minute).

**The latency criterion — exact thresholds.** Written before the first run; unchanged:

| Criterion | Threshold |
|---|---|
| All tickets finish | 13 of 13 `finished`; no abandoned ticket, no failed turn |
| API latency | `start`, `send`, `poll`, `result`: **p95 < 500 ms** (nearest-rank, over the 13-ticket phase, uploads and conversions running), and no 5xx or connection error |
| No throttling | 0 learner requests refused with HTTP 429 |
| No duplicates | one scoring call and one answer per reply; one attempt per finished ticket |
| Videos | all three ready; the last within 1.5 × (3 × the single-video baseline) |
| Reply latency | send → customer reply visible: p95 < 30 s (synthetic model latency) |

**Where it stands, honestly: every criterion passes in every run except API latency, and `start` p95
misses more often than it passes when three 109 MB uploads arrive in the same second as 13
simultaneous starts.** With 13 starts, p95 is the single slowest request, so one slow start decides it.

| Setup (gunicorn, uploads arriving with the tickets) | runs | `start` p95 per run (ms) | pass |
|---|---|---|---|
| shipped: 3 workers × 4 threads, ffmpeg capped and niced | 8 | 571, 429, 396, 520, 521, 394, 545, 577 | **3 of 8** |
| 6 workers × 4 threads | 2 | 725, 923 | 0 of 2 |
| 8 workers × 1 thread | 3 | 528, 518, 460 | 1 of 3 |
| database connections kept 60 s (tried, then reverted) | 3 | 550, 479, 5,339 | 1 of 3 |
| *control:* the same 13 tickets, **no videos** | 2 | 211, 240 | 2 of 2 |
| *the uploads begin 3 s after the tickets start* | 1 | 283 | 1 of 1 |

The other endpoints in the shipped setup are mostly inside the bar: `send` p95 170–290 ms, `poll` p95
100–190 ms, `result` p95 ≤ 115 ms — with exceptions. One run (3 of 3 in the batch of three, load average
9.2) had a cluster of 12 polls at 0.5–1.2 s around the 7-second mark, which is unexplained, and a few
single requests of 0.5–0.7 s appear elsewhere.

**What is established:**
* The misses need the uploads: without videos, or with the uploads 3 s later, `start` passes (≤ 283 ms),
  and in the runs that counted them most slow requests overlapped an upload being received.
* The time is spent inside the handler, not only waiting for it: gunicorn's own timer puts the 13
  simultaneous `start`s at p50 150–380 ms (control without videos: 107 ms); the client adds 100–200 ms
  on top. Warm, in-process, a `start` costs about 40 ms.
* It is not the disk or the database: commits during the upload burst had p95 32 ms, max 210 ms.
* It is not the web tier's sizing: more workers made it worse, single-threaded workers didn't help, and
  connection reuse didn't help (and once coincided with a 5.3 s `start` I could not explain, so I
  reverted it).

**What is not established:** the mechanism. Load average during these runs reached 5–14 on 8 CPUs on a
laptop that was also running a desktop and a browser, so CPU saturation by the uploads' receipt plus two
conversions plus the practice worker is the leading suspect, but I have not proven it. The options are a
decision for you: accept it as a property of three simultaneous 109 MB uploads (a rare event beside 13
simultaneous starts), move big uploads off the Django request path (a direct-to-storage or raw-stream
upload), or rerun on production-like hardware with nginx in front before deciding.

**What did fix a real problem along the way** (round 2 → 3 of the investigation): an unbounded ffmpeg
decode check took every core when two conversions finished together and stalled *all* requests for 2 s.
Capping it at 2 threads and running ffmpeg under `nice` (`MEDIA_FFMPEG_NICE`, default 10) removed that
cluster (`send` p95 1.3 s → 0.2–0.3 s; the 2-second stalls on every endpoint are gone). The cost: a conversion is slower when
the machine is busy (single video 16 s → 19–24 s; the three under load 21/21/36 s → about 22–36/22–36/41–60 s).
My first explanation (the dev server parsing uploads) was wrong; the overlap counts and a one-conversion
probe showed it.

* **Driver note:** gunicorn closes idle keep-alive connections after 2 s and the driver polls every
  ~2 s, so about 40 % of requests found their connection just closed. A browser retries that silently on
  a fresh connection, and the driver now does too, once (a retried send is safe: replies are idempotent
  on `client_id`). The count is printed in every report; my first gunicorn run, without the retry,
  recorded 109 spurious connection errors that the server log shows never reached it.
* What this does **not** show: how the real provider behaves (latency, real 429s, cost), more than 13
  at once, nginx in front, or other hardware. A short live run needs `OPENAI_API_KEY`
  (`scripts/simbot_live_check.py`).

## Extraction path

The engine imports nothing from Django and talks to the model only through the `LLMClient`
protocol; `apps/bot_sim` owns storage, queues and limits. The result and session API mirror the
HALO outcome shape (architecture §6), so moving to a separate service means wrapping the engine and
moving the adapters. A test drives the engine through a second, in-memory adapter and another
asserts the package can be imported with Django absent.

## Known limits

* Scores are model opinions without ground truth (see above); a learner can paste the customer's
  message into an external AI — nothing here can prevent it.
* The engine shares the backend's failure domain (the extraction path is the mitigation).
* No live (streaming) chat, no per-scenario reference answers wired into scoring yet (a Zendesk
  agent's accepted reply could ground it later), no cross-learner "worth a look" queue beyond the
  scenario review filters.
* **Little live Zendesk testing.** The reader, the authorship rules and the whole import were
  tested against a fake Zendesk and a scripted model, including a real-browser run of the Console
  import. A live audit (30 tickets examined, 13 judged genuine) and one live import have since been run
  in development; that is a small sample, and form names, rate limits and ticket shapes may still
  need the rules adjusted. Rewritten questions can still be poor: the strict checks, dedupe, skip-and-flag, the
  undo and the off switch are mitigations, not guarantees, and an automatically approved question
  can reach a scored ticket before a person has read it.
* **The nightly top-up has only been exercised with fakes** (and its switch in a real browser). Its
  first live run happens the first night it fires with the switch on; the global approved count
  can be healthy while an activity filtered to one topic or customer type has none.
* **Not verified:** the Docker image (Docker isn't installed on the development machine, so the
  gunicorn `CMD` and the Compose services are untested as built), nginx in front of gunicorn, and any
  live model provider (no API key was available — only the scripted fake has been run; real latency,
  429s, cost and score variance are unmeasured; `scripts/simbot_live_check.py` exists for that).
* The latency criterion in the load test does not pass reliably when large uploads arrive with a burst of
  starts (see above).
