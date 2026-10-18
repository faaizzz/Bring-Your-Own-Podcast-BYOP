# Scheduling

A show runs by itself on a schedule, or only when you press **Generate now**.

`schedule_kind` is `manual` (never automatic), `daily`, `weekly` (`schedule_weekday`, 0 = Monday) or
`monthly` (`schedule_monthday`, 1-31). `schedule_time` is the wall-clock time in the show's
`timezone` (an IANA name such as `Europe/Berlin`), so it keeps its local time across daylight-saving
changes. In a month that is too short, a day beyond its end means its last day (31 → Feb 28/29,
Apr 30). A time the clock skips in spring runs right after the jump; one that happens twice in
autumn uses the first.

## How it fires

The `beat` service runs `byop.schedule_tick` every minute. It locks the shows whose `next_run_at` has
passed (and that are not paused) with `FOR UPDATE SKIP LOCKED`, creates a run with trigger
`schedule`, and moves `next_run_at` to the next slot, all in one transaction. So:

- overlapping ticks never start a show twice;
- after downtime you get **one** catch-up run, not one per missed slot;
- a slot is skipped while the show still has a run queued or running (a run waiting for review does
  not block the next one);
- shows with a schedule but no `next_run_at` (created before scheduling existed) get one without
  running.

**`beat` must be running** for schedules to fire (compose starts it). `next_run_at` is recomputed
whenever the schedule, the time zone or `paused` changes.

## Pausing

`POST /api/shows/{id}/pause` stops the schedule (manual runs still work) and clears `next_run_at`;
`POST /api/shows/{id}/resume` continues from the next slot after now; the missed slots are not made
up. The show page has a **Pause schedule** button and the dashboard lists what is coming in the next
7 days. Reviewing: set `auto_publish` for fully automatic shows, otherwise each scheduled episode
waits as a draft ([review](review.md)).

Costs add up unattended: check the [costs](costs.md) page and prefer an inexpensive model for
scheduled shows.
