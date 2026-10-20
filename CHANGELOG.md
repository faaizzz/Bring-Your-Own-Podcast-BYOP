# Changelog

All notable changes to BYOP are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). When a release is tagged, replace "unreleased" in its
heading with the date (see [docs/releasing.md](docs/releasing.md)).

## [Unreleased]

### Added

- **Documentation:** the README and the docs describe styles, personas, Design with AI, the voice
  model, the wait between requests and the discovery model; `make screenshots` takes pictures of
  them (Styles, Personas, the Design with AI dialog, the Voice model dropdown, the Discovery model
  card).

- **Discovery model in Settings:** choose the model that searches the web for sources under
  Settings › Integrations › Discovery model. It takes precedence over `DISCOVERY_LLM_*`, the show's
  model and the instance default, is checked for web search when saved, and is used by the Discover
  dialog, the wizard, the worker and web-search sources (`GET/PUT/DELETE /api/settings/discovery-model`).
  New table `user_settings` (migration `0012`) for per-user defaults.
- **Voice model picker:** a speaker on OpenRouter, OpenAI, ElevenLabs or a connection chooses the
  speech model from a searchable list before the voice (`GET /api/voices/models`); OpenRouter's
  speech models and their voices come from its `output_modalities=speech` listing, and a model is
  required for OpenRouter speakers.
- **Design with AI:** a button in the style editor, the persona editor and a speaker's persona
  field drafts a style or persona from a sentence (`POST /api/assist/style`, `/persona`); the draft
  fills the form and nothing is saved until you save. The cost is recorded under the stage
  `assist` and traced in Langfuse.
- **Persona library:** keep reusable speaker personas (with an optional default voice) under
  Settings › Personas; apply one to a speaker with *From library* or keep a speaker's with *Save to
  library*. Five starter personas for every user (`personas` table, migration `0015`;
  `GET/POST/PATCH/DELETE /api/personas`).
- **Styles:** read exactly what each built-in style tells the model, duplicate one into your own,
  or write a new one (Settings › Styles); a show picks a built-in or custom style (`styles` table
  and `shows.custom_style_id`, migration `0014`; `GET/POST/PATCH/DELETE /api/styles`).
- **Wait between requests:** a per-provider and per-connection delay (0–60 s) between calls, shared
  across workers through Redis, to stay under low rate limits; waits show in the run log.
- **Connections** (any number of OpenAI-compatible servers with custom headers), **searchable
  dropdowns** everywhere, **web-search validation** for source discovery and minimal vs. full builds
  (`make up` / `make up-full`).

## [0.1.0] - 2026-10-19

The first release: a self-hosted app that turns your sources into a scheduled, multi-speaker AI
podcast with its own RSS feed.

### Added

- **Shows and speakers:** topic, style (news briefing, conversational, deep dive, interview),
  language, length, schedule, cover and a cast of named speakers with their own voices (and fallback
  voices); a step-by-step wizard and a settings tab.
- **Sources:** RSS/Atom feeds, web pages and web-search queries, with validation, automatic discovery
  from a topic, and a guard that refuses private addresses.
- **Generation pipeline:** ingest, de-duplicate (trigram similarity), rank, write the script, voice it,
  mix with ffmpeg (gaps, intro/outro, music bed, -16 LUFS) and finalize; staged, cancellable, retried
  on temporary errors and reaped when stuck; live run view over Server-Sent Events.
- **Review flow:** edit the script, re-synthesize, approve or reject a draft, or auto-publish.
- **Scheduling:** daily, weekly and monthly runs in the show's time zone (DST-safe), catch-up after
  downtime, pause and resume.
- **Public podcast feed** (`/feeds/<slug>.xml`) with iTunes and Podcasting 2.0 tags, and public episode
  audio with `Range` support.
- **Providers:** OpenRouter, OpenAI and any OpenAI-compatible server (Ollama, LM Studio, vLLM) for
  language models; OpenAI, ElevenLabs, OpenRouter and local Kokoro for voices; keys from `.env` or
  saved encrypted in the app.
- **Costs and observability:** usage recorded per call, per-run, per-show and monthly cost overview with
  charts and CSV export, cost estimate before generating, editable price table, optional Langfuse
  tracing (with a self-hosted compose profile).
- **Web app:** dashboard with onboarding, shows, episodes, history with filters, costs, settings,
  light and dark mode.
- **Storage:** local volume or any S3-compatible service.
- **Operations:** docker compose stack with optional Kokoro, S3 and Langfuse profiles; multi-arch images
  on GHCR (`BYOP_VERSION`); end-to-end browser test with mock model and voice servers.
- **Documentation:** quickstart, configuration reference, architecture, publishing to podcast
  directories, backup and restore, a guide to adding providers, contributing guide, code of conduct
  and security policy.

### Security

- One admin login with signed, `httpOnly` `SameSite=Lax` sessions and rate-limited login; every route
  is guarded by default (a test enforces it).
- Provider keys encrypted at rest and masked everywhere; secrets redacted from logs.
- Server-side fetches of user-supplied URLs refuse private and link-local addresses.
- nginx sets a Content-Security-Policy, `X-Frame-Options`, `X-Content-Type-Options`, a referrer and a
  permissions policy, and HSTS when served over https; request bodies are limited to 1 MB except
  for cover and audio uploads.
- No CORS: the API and feed are same-origin only.
- Rate limits on the public feed and audio routes (`PUBLIC_FEED_RATE_PER_MINUTE`,
  `PUBLIC_MEDIA_RATE_PER_MINUTE`).
- Dependency audits (`pip-audit`, `npm audit`) run in CI on every push and weekly; no known
  vulnerabilities at release.

### Known limitations

- Single user: one admin account (the data model is ready for more users).
- Local Kokoro voices on a CPU are slow (a few minutes for a short episode); use a GPU image or a
  hosted voice for long episodes.
- The bundled Langfuse profile needs about 2 GB of memory.
