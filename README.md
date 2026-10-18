# BYOP — Bring Your Own Podcast

[![CI](https://github.com/faaizzz/Bring-Your-Own-Podcast-BYOP/actions/workflows/ci.yml/badge.svg)](https://github.com/faaizzz/Bring-Your-Own-Podcast-BYOP/actions/workflows/ci.yml)

**Your sources in, a podcast out.** BYOP is a self-hosted, open-source app that turns the feeds,
pages and searches you care about into a recurring, multi-speaker AI podcast with its own RSS feed.
Bring your own language-model and voice keys, or run everything locally for free, and keep full
control of your data.

![The dashboard: tiles, latest episodes with a player, what is coming up](docs/images/dashboard.png)

## What you get

- **Shows** with a topic, a style (news briefing, conversational, deep dive, interview), a schedule
  and a cast of named speakers, each with their own voice.
- **Sources:** RSS feeds, web pages and web-search queries, found for you from just a topic, or
  hand-picked. Stories are collected, de-duplicated and ranked; the best ones are covered.
- **Scripts** written by the model of your choice as a natural dialogue between your speakers.
- **Voices** from OpenAI, ElevenLabs, OpenRouter or local Kokoro, mixed with ffmpeg: gaps,
  intro/outro, a music bed, -16 LUFS loudness.
- **Review before you publish:** edit the script, re-voice it, approve or reject. Or auto-publish.
- **A public RSS feed** that works in Apple Podcasts, Spotify, Pocket Casts and every other app.
- **On a schedule:** daily, weekly or monthly, in your time zone, with pause and catch-up.
- **Know the cost:** every call is recorded; per-run, per-show and monthly spend with charts, an
  estimate before you generate, optional [Langfuse](docs/langfuse.md) tracing.

| Run, live | Episode review |
| --- | --- |
| ![A run: stage timeline, live log and cost](docs/images/run.png) | ![Reviewing an episode: player, coloured script, sources](docs/images/episode-review.png) |

| Costs | A show and its feed |
| --- | --- |
| ![Costs: tiles, monthly chart, providers](docs/images/costs.png) | ![A show with its feed address](docs/images/show.png) |

*(The pictures show the end-to-end test's mock model and voices.)*

## Quickstart

You need Docker with the compose plugin. Three commands:

```sh
git clone https://github.com/faaizzz/Bring-Your-Own-Podcast-BYOP.git
cd Bring-Your-Own-Podcast-BYOP
make up        # creates .env, generates BYOP_SECRET_KEY, builds and starts everything
```

Open <http://localhost:8080> and sign in with `admin@example.com` / `change-me-now` (set your own
`BYOP_ADMIN_EMAIL` and `BYOP_ADMIN_PASSWORD` in `.env` before exposing the app). The dashboard walks
you through the first episode:

1. **Settings › Integrations:** add an OpenRouter or OpenAI key (or a local model, below).
2. **Shows › New show:** a title and a topic, pick the voices, a model and, optionally, a schedule.
3. **Sources tab:** *Discover sources* from the topic, or add feeds by hand.
4. Press **Generate now**, watch the run, review the episode and approve it.
5. Copy the show's feed address into your podcast app. [Publishing](docs/publishing.md) explains how
   to put it on the internet and into Apple Podcasts and Spotify.

### Zero-cost mode

No paid keys? Run the voices locally with [Kokoro](docs/providers.md#local-voices-with-kokoro-no-api-key)
and the language model with [Ollama](docs/providers.md#zero-cost-mode-kokoro-voices-and-a-local-model):

```sh
make up-kokoro                 # BYOP plus a free local text-to-speech server
ollama pull qwen2.5:14b        # on your machine; then add it under Integrations › OpenAI-compatible
```

### Providers

| | OpenRouter | OpenAI | ElevenLabs | Kokoro (local) | OpenAI-compatible (Ollama…) |
| --- | :-: | :-: | :-: | :-: | :-: |
| Language models | ✓ | ✓ | | | ✓ |
| Voices | ✓ | ✓ | ✓ | ✓ | |
| Cost reported by the provider | ✓ | | | | |
| Needs a key | ✓ | ✓ | ✓ | | |

Details, and how to add another provider: [providers](docs/providers.md).

## Everyday commands

`make up` · `make down` · `make logs` · `make up-kokoro` · `make up-minio` (S3 storage) ·
`make up-langfuse` (tracing) · `make check` (lint, types, tests) · `make e2e` (browser test) ·
`make help` lists them all. In development `docker-compose.override.yml` mounts the API source for
hot reload; for a production-like run use `docker compose -f docker-compose.yml up -d --build`.

## Documentation

**Use it**

- [Configuration: every environment variable](docs/configuration.md)
- [Model providers (OpenRouter, OpenAI, Ollama, Kokoro) and adding one](docs/providers.md)
- [Shows](docs/shows.md) · [Sources](docs/sources.md) · [Scheduling](docs/scheduling.md)
- [Reviewing episodes](docs/review.md) · [Dashboard](docs/dashboard.md)
- [Podcast feed](docs/feed.md) · [Publishing to directories](docs/publishing.md)
- [Usage and costs](docs/costs.md) · [Langfuse tracing](docs/langfuse.md)
- [Media storage (local or S3) and covers](docs/storage.md)
- [Backup and restore](docs/backup.md) · [Secrets and key rotation](docs/security.md)

**How it works**

- [Architecture](docs/architecture.md)
- [Runs (the pipeline)](docs/runs.md) · [Ingest](docs/ingest.md) · [Choosing stories](docs/ranking.md) ·
  [Scripts](docs/scripts.md) · [Voicing](docs/tts.md) · [Episode audio](docs/audio.md)
- [End-to-end test](docs/e2e.md)

## Contributing

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). Report security problems privately as described in
[SECURITY.md](SECURITY.md). The roadmap lives in the
[GitHub issues](https://github.com/faaizzz/Bring-Your-Own-Podcast-BYOP/issues) and the
[project board](https://github.com/users/faaizzz/projects/2).

## License

[MIT](LICENSE)

The admin UI theme is derived from the MIT-licensed
[Gradient Able](https://github.com/codedthemes/gradient-able-free-admin-template)
free template by CodedThemes; its licence notice is kept in
[`apps/web/src/theme/LICENSE-gradient-able`](apps/web/src/theme/LICENSE-gradient-able).
