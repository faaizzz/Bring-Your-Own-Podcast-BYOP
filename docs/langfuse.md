# Langfuse tracing

[Langfuse](https://langfuse.com) shows every model call of every run: the prompt, the answer, the
tokens and the cost. BYOP sends it automatically when Langfuse is set up, and does nothing when it
is not.

## What a trace contains

One **trace per run**, named after the show, with the show as its *session* (so all runs of a show
group together) and the run's trigger and the show's style as tags. Inside it:

- a **span per stage** (`ingest`, `rank`, `script`, `tts`, `mix`, `finalize`), marked as an error
  when the stage failed and as a warning when the run was cancelled;
- a **generation per language-model call** (ranking, script, web-search sources, ...): model,
  prompt, answer, input/output tokens and the cost, as BYOP records it (see [costs](costs.md));
- a **span per voice call**: provider, characters, cost, latency, the speaker and voice;
- the run's result as the trace's output.

Prompts and answers longer than 20,000 characters are cut. A stage that is retried after a
temporary error keeps one span.

Tracing never makes a run fail or wait: events are collected in memory, sent once per stage with a
4-second timeout, and anything that goes wrong (host down, wrong keys, a server error) is logged and
dropped. The run's page has an **Open trace in Langfuse** link once it has a trace (`trace_url` in
`GET /api/runs/{id}`); `runs.trace_id` holds the trace id.

## Turning it on

Give BYOP a Langfuse project's keys, either in **Settings › Integrations › Langfuse** or in `.env`:

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com      # or your own server
LANGFUSE_PUBLIC_URL=                          # only if your browser needs another address
```

Runs that start afterwards are traced. `LANGFUSE_HOST` is where BYOP's own containers reach
Langfuse; `LANGFUSE_PUBLIC_URL` is what the trace links in the app use when your browser reaches it
differently (for example `http://localhost:3000`).

## Self-hosting it with BYOP

```sh
make up-langfuse        # = docker compose --profile langfuse up -d --build --wait
```

This adds Langfuse 3 and what it needs (its own Postgres, ClickHouse, Redis and an S3-compatible
store for events; none of it shares data with BYOP) on `http://localhost:3000`, bound to your own
machine only. A project with fixed keys is created on the first start, and you can sign in with
`BYOP_ADMIN_EMAIL` / `BYOP_ADMIN_PASSWORD`. To trace into it add this to `.env` and restart the
stack:

```
LANGFUSE_PUBLIC_KEY=pk-lf-byop-local
LANGFUSE_SECRET_KEY=sk-lf-byop-local
LANGFUSE_HOST=http://langfuse-web:3000
LANGFUSE_PUBLIC_URL=http://localhost:3000
```

Generate an episode, open its run and follow **Open trace in Langfuse**.

The local keys, salts and passwords in `docker-compose.yml` are defaults for a machine nobody else
can reach. If you expose Langfuse, set your own `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
`LANGFUSE_SALT`, `LANGFUSE_ENCRYPTION_KEY` (64 hex characters), `LANGFUSE_NEXTAUTH_SECRET`,
`LANGFUSE_DB_PASSWORD`, `LANGFUSE_CLICKHOUSE_PASSWORD`, `LANGFUSE_REDIS_PASSWORD` and
`LANGFUSE_S3_*` in `.env` before the first start (they cannot be changed afterwards without
resetting its data). The images are large (ClickHouse alone is several hundred MB) and the stack
needs about 2 GB of memory.

## How it works

`services/langfuse.py` talks to Langfuse's public ingestion API (`POST /api/public/ingestion`,
basic auth with the two keys) directly, with no SDK. Providers already report every finished call
for [cost capture](costs.md); the tracer listens to the same reports, so no pipeline code knows
about tracing.
