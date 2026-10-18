# Dashboard

The home page answers three questions: what is happening, what is coming, what did it cost. It is
filled by a single request, `GET /api/dashboard`, and refreshes every few seconds while a run is
working.

| Part | Meaning |
| --- | --- |
| Shows | How many shows you have |
| Episodes this month | Episodes created since the 1st (UTC), and how many drafts still wait for review |
| Spend this month | Sum of the usage recorded this month ([costs](costs.md)) |
| Success rate | Of the runs that ended in the last 30 days, the share that made an episode (`succeeded` or `awaiting_review`; cancelled runs do not count). `—` before any ended |
| Running now | Queued and running runs with their stage and progress |
| Needs attention | Shows whose newest run failed in the last 7 days, with the reason and a **Retry** button (shown while nothing is running for the show; it asks for confirmation with the cost estimate like Generate now). A later run, whatever its outcome, replaces the failure |
| Coming up | Scheduled runs due in the next 7 days (paused and manual shows are left out) |
| Latest episodes | The five newest episodes with a small player |

Until the first episode exists the page shows a **getting started checklist** instead: connect a
language model (a key under Settings › Integrations or in `.env`), create a show, generate the first
episode. Each step ticks off by itself; `onboarding` in the response says which are done.

Everything is limited to your own data.
