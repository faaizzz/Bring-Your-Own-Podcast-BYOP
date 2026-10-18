# Usage and costs

Every call to a language model or a voice is recorded in `usage_events` with the show, run and
stage it belongs to, so you can see what each episode cost.

## What is recorded

One row per call (a structured reply that needed a repair counts as one call with the tokens of
both requests): `kind` (`llm` or `tts`), `provider`, `model`, `stage` (`discovery`, `ingest`,
`rank`, `script`, `tts`, ...), `input_tokens` / `output_tokens` (language models) or `characters`
(voices), `latency_ms`, `cost_usd` and where the cost came from (`cost_source`).

Providers only *report* the call (`byop.providers.common.record_usage`); they never touch the
database. A `UsageCollector` (`services/usage.py`) collects the reports and the owner of the work
stores them: a run stores each stage's calls when the stage ends (and on every progress update,
so a long stage shows its spend as it goes), source discovery and voice previews use
`capture_usage`. Calls made outside both (a dry-run CLI command) are not recorded.

## Where the cost comes from

In this order:

1. **The provider's own figure** (`cost_source = provider`), when it reports one: OpenRouter
   returns `usage.cost` for every request.
2. **A price** (`price_table`): `byop/pricing.yaml` is a table of approximate list prices
   (per 1M tokens for models, per 1M characters for voices), with your overrides on top. A model
   matches by the longest id that is a prefix of its name, so `gpt-4.1-mini-2025-04-14` uses the
   `gpt-4.1-mini` entry.
3. **Unknown** (`unknown`): neither is available. The cost is stored as 0 and the call is counted
   in `unknown_calls`, so a total is a lower bound whenever that number is not 0.

Prices change and plans differ, so set your own under **Settings › Pricing** (or
`PUT /api/pricing/overrides`); they apply to calls made from then on. A voice price is set per
provider (`elevenlabs`) or per model (`openai:tts-1-hd`). Local voices (Kokoro) are free.

## Run totals

When a run ends (finished, failed or cancelled) its `cost_usd`, `llm_cost_usd` and `tts_cost_usd`
are set to the sums of its events, so they always equal the sum of the rows.

## API

| Method | Path | |
| --- | --- | --- |
| `GET` | `/api/costs/summary` | Spend grouped by `group_by=show\|month\|provider\|stage`, optional `from` and `to` (days, UTC, inclusive). The response also has `episodes` (runs in the period that made an episode) and `avg_episode_cost_usd` (their mean cost). Each group has `cost_usd`, `llm_cost_usd`, `tts_cost_usd`, `calls`, `unknown_calls`, tokens and characters, and the response carries the `total` |
| `GET` | `/api/costs/export.csv` | The usage events of the period (`from`, `to`; all time by default) as a CSV file, oldest first. Show titles that would run as a spreadsheet formula are prefixed with `'` |
| `GET` | `/api/runs/{id}/usage` | A run's calls grouped by stage, provider and model, with `unknown_calls` per line |
| `GET` | `/api/shows/{id}/estimate` | What one episode of the show should cost, from its target length, model and voices (`llm_usd`, `tts_usd`, `total_usd`, with `notes` for anything it could not price) |
| `GET` | `/api/pricing` | The effective prices (`source`: `default` or `override`) |
| `PUT` | `/api/pricing/overrides` | Set your price: `{kind: "llm", name, input_per_million, output_per_million}` or `{kind: "tts", name, per_million_chars}` |
| `DELETE` | `/api/pricing/overrides?kind=&name=` | Back to the default price |

Months are calendar months in UTC. Usage rows outlive their show and run (the references are
cleared), so history stays accurate after a show is deleted; those rows are grouped as "Deleted show".

The estimate assumes about 900 spoken characters per minute and the show's number of stories, and
takes a model's price from the price table, else from the provider's model list (OpenRouter
publishes prices there). It is a guide, not a quote.

## In the app

- **Costs** shows four tiles (this month, last month, the average cost of an episode, the most
  expensive show), a stacked bar chart of the last 12 months (language models and voices), a donut
  of the providers that charged anything, and a table per show. The period filter applies to the
  table, the donut and the CSV export. If any call has no known price a banner says so and the
  affected rows are marked "unpriced": the figures are then a minimum.
- A run's page and an episode's page list the **cost by stage and model**.
- **Generate now** asks for confirmation and shows the estimate first (or "unknown" with the
  reason when a price is missing).
