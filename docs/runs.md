# Runs

A **run** is one attempt to produce an episode: a pipeline of stages with a status, a progress
bar and a log. Everything runs in the Celery worker.

| Method | Path | |
| --- | --- | --- |
| `POST` | `/api/shows/{id}/runs` | Queue a run (`202`; `409` if the show already has one queued or running) |
| `GET` | `/api/runs` | List, newest first; filters `show_id`, `status`, paging `limit` (≤ 200) and `offset` |
| `GET` | `/api/runs/{id}` | The run with its log (`events`, oldest first) |
| `POST` | `/api/runs/{id}/cancel` | Stop it (`409` if it already ended) |

Try it:

```sh
curl -b cookies.txt -X POST http://localhost:8080/api/shows/<id>/runs
curl -b cookies.txt http://localhost:8080/api/runs/<run id>      # status, stage, progress, events
```

## Status

`queued` → `running` → `succeeded` | `awaiting_review` | `failed` | `cancelled`. A show can have
only one run that is `queued` or `running`; the database enforces it (a partial unique index), so
two requests at the same moment cannot both win. A run `awaiting_review` is waiting for a person,
not working, and does not block the next one.

## Stages

`ingest` (0–20 %) → `rank` (20–30) → `script` (30–55) → `tts` (55–85) → `mix` (85–95) →
`finalize` (95–100). They are plain functions in `byop/pipeline/stages/` that take a
`RunContext` (the run, its show, a session, settings and a credential resolver); the wiring is
`byop/pipeline/orchestrator.py`. Today `ingest`, `rank` and `script` are real (the script becomes a
draft episode, see [scripts](scripts.md)); `tts` and `mix` are placeholders that log "Not
implemented yet", and `finalize` ends the run and marks the stories as used by the draft.

The chain is one Celery task per stage (`byop.run_stage`), built by
`byop.tasks.pipeline.build_chain`. Each stage:

- sets the run's `stage`, `progress` and `celery_task_id`, and appends to the log (`run_events`:
  time, level `info|warning|error`, stage, message, optional JSON `data`);
- calls `ctx.progress(fraction)` while it works (this is also the run's heartbeat) and
  `ctx.checkpoint()` between steps, which stops it if the run was cancelled.

## When things go wrong

- **Transient errors** (a stage raises `TransientStageError`, e.g. a provider hiccup) are retried by
  Celery with a delay that doubles from 5 s up to 120 s, at most `RUN_STAGE_MAX_RETRIES` (3)
  times. If it still fails the run is failed.
- **Terminal errors** (`StageFailed`, or any other exception) fail the run at once: `status` is
  `failed` and `error` holds the reason (an unexpected exception shows its type and message). The
  stages after it find the run ended and do nothing.
- **Cancelling**: a queued run is cancelled on the spot. A running one is flagged
  (`cancel_requested`) and stops at its next checkpoint, or before its next stage starts, and then
  shows as `cancelled`; the current task is also revoked, best effort.
- **Stuck runs**: a Celery beat task (`byop.reap_runs`, every `RUN_REAPER_INTERVAL_S`, 60 s) fails
  every queued or running run whose row has not changed for `RUN_TIMEOUT_MINUTES` (60), with the
  message "Timed out: no progress for N minutes". So no run can stay `running` forever, even if
  the worker died. Stages that take long must report progress regularly.
- Whichever way a run fails or is cancelled, the stories it reserved are given back
  (see [choosing stories](ranking.md)).

| Variable | Default | |
| --- | --- | --- |
| `RUN_TIMEOUT_MINUTES` | `60` | No progress for this long: the run is failed |
| `RUN_STAGE_MAX_RETRIES` | `3` | Retries of a stage after transient errors |
| `RUN_REAPER_INTERVAL_S` | `60` | How often stuck runs are looked for (needs the `beat` service) |
