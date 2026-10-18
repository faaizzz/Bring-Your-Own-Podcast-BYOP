# BYOP — Bring Your Own Podcast

[![CI](https://github.com/faaizzz/Bring-Your-Own-Podcast-BYOP/actions/workflows/ci.yml/badge.svg)](https://github.com/faaizzz/Bring-Your-Own-Podcast-BYOP/actions/workflows/ci.yml)

Self-hosted, open-source app that turns the sources you care about into a
recurring, multi-speaker AI podcast with its own RSS feed. Bring your own LLM
and text-to-speech keys (or run everything locally) and keep full control.

## Features

- Create shows with a topic, style, schedule and a cast of named speakers
- Auto-discover or hand-pick RSS / URL / web-search sources
- Ingest, de-duplicate, rank and select the stories worth covering
- LLM-written multi-speaker scripts, synthesised with OpenAI, ElevenLabs,
  OpenRouter or local Kokoro voices, then mixed with ffmpeg
- Review drafts before publishing, or auto-publish on a schedule
- Public RSS feed that works with any podcast app
- Per-generation cost tracking and optional Langfuse tracing

## Quickstart

Requires Docker with the compose plugin.

```sh
cp .env.example .env   # optional: `make up` creates it and generates BYOP_SECRET_KEY
make up                # builds and starts postgres, redis, api, worker, beat, web
```

Open <http://localhost:8080> and sign in with `BYOP_ADMIN_EMAIL` / `BYOP_ADMIN_PASSWORD`
from your `.env` (change the example password before exposing the app). The API health check is at
<http://localhost:8080/api/health>. Every variable is documented in
[`.env.example`](.env.example). Run `make migrate` to apply database migrations. Other targets: `make down`, `make logs`,
`make migrate`, `make check` (lint + typecheck + tests), `make fmt`.

No paid API keys? `make up-kokoro` (or `docker compose --profile kokoro up -d`) also starts a
local, free [Kokoro](docs/providers.md#local-voices-with-kokoro-no-api-key) text-to-speech
server that is preselected whenever no paid TTS key is configured.

`docker-compose.override.yml` bind-mounts the API source for hot reload in
development; for a production-like run use
`docker compose -f docker-compose.yml up -d --build`.

## Documentation

- [Model providers (OpenRouter, OpenAI, Ollama, Kokoro)](docs/providers.md)
- [Secrets and key rotation](docs/security.md)

## Roadmap

The roadmap lives in the
[GitHub issues](https://github.com/faaizzz/Bring-Your-Own-Podcast-BYOP/issues)
and the [project board](https://github.com/users/faaizzz/projects/2).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)

The admin UI theme is derived from the MIT-licensed
[Gradient Able](https://github.com/codedthemes/gradient-able-free-admin-template)
free template by CodedThemes; its licence notice is kept in
[`apps/web/src/theme/LICENSE-gradient-able`](apps/web/src/theme/LICENSE-gradient-able).
