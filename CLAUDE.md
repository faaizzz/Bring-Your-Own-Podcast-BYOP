# CLAUDE.md — BYOP (Bring Your Own Podcast)

Self-hosted app that turns a show's sources into a scheduled, multi-speaker AI
podcast with a public RSS feed. This file is the contract for every story: read
it, then read the GitHub issue, then implement exactly that issue.

## Workflow
- Roadmap = GitHub issues #1–#36 in `faaizzz/Bring-Your-Own-Podcast-BYOP`, tracked on project board 2 (owner `faaizzz`).
- Pick the Todo item with the lowest `Order` (= issue number); every issue under "Depends on" must be closed first.
- Full steps: `docs/IMPLEMENTATION_WORKFLOW.md`. Work **directly on `main`** — no branches, no PRs.
- Implement the issue's scope and nothing more; honour its "Out of scope".
- Done means: every acceptance criterion met, `make check` green, docs updated, commit pushed with `Closes #N`.
- Never weaken or skip tests to get green. Never commit secrets or a real `.env`.

## Stack
- API: Python 3.12, FastAPI, pydantic v2 + pydantic-settings, async SQLAlchemy 2 + asyncpg, Alembic, Celery (+beat) on Redis, structlog, httpx.
- Data: PostgreSQL 16 (with `pg_trgm`), Redis 7. Audio mixing with ffmpeg.
- Web: Vite + React 18 + TypeScript (strict), react-bootstrap/Bootstrap 5, react-router 6, TanStack Query, react-hook-form + zod, Gradient Able admin look.
- Runtime: docker compose (`api`, `worker`, `beat`, `web`, `postgres`, `redis`; optional profiles `minio`, `kokoro`, `langfuse`).

## Layout
```
apps/api/byop/        FastAPI package
  main.py             app factory
  config.py           pydantic-settings (reads .env)
  db.py               async engine + session dependency
  redis_client.py     shared async Redis client + dependency
  logging.py          structlog JSON logging with request id
  worker.py           Celery app + tasks entrypoint
  api/                routers, ONE FILE PER RESOURCE (shows.py, speakers.py, ...)
  services/           domain logic — never in routers (`storage.py`: media storage seam; everything of a show lives under `shows/<id>/`)
  models/             SQLAlchemy models
  schemas/            pydantic request/response models
  providers/llm/      LLM provider abstraction
  providers/tts/      TTS provider abstraction
  security/           crypto, auth helpers
apps/api/alembic/     migrations
apps/api/tests/       pytest (mirrors the byop/ tree)
apps/web/src/
  theme/              Gradient Able SCSS/variables/fonts (+ LICENSE-gradient-able); _overrides.scss holds BYOP additions incl. dark mode
  layout/             sidebar, header, breadcrumb, shell
  pages/<area>/       one folder per area (dashboard, shows, history, costs, settings, auth)
  lib/                api client (api.ts), helpers
docker/               Dockerfiles, nginx.conf
docs/                 user + contributor documentation
.github/              CI workflows, issue templates
```
New directories or modules must follow these names; update this section if the layout changes.

## Python conventions
- Format and lint with `ruff` (line length 100); `mypy --strict` must pass; no untyped defs, no bare `Any` without a comment.
- Everything I/O is `async`; use async SQLAlchemy sessions injected via dependency. No blocking calls in request handlers.
- pydantic v2 models for all request/response and settings; never return ORM objects from routers.
- Money is `Decimal`/`Numeric`, never float. Timestamps are timezone-aware UTC.
- Routers are thin: parse input → call a service → return a schema. Every service query filters by `user_id`.
- Provider keys are read only through `CredentialResolver` (`services/credentials.py`: user override encrypted with Fernet from `BYOP_SECRET_KEY` → `.env` → `ProviderNotConfigured`; enforced by `tests/test_provider_key_access.py`). Providers receive a resolved `ProviderConfig`. API responses mask secrets (`sk-…1234`); `logging.py` redacts secret-looking keys/values. Rotating `BYOP_SECRET_KEY`: `docs/security.md`.
- Structured logging via structlog; no `print`.
- LLM calls only through `byop/providers/llm` (`get_llm(...).complete(..., metadata=CallMetadata(...))`); thin wrapper over the OpenAI SDK, no LangChain. The SDK defaults to httpx2, so providers pass an explicit `httpx` client — keep that, it is what makes `respx` mocks work. Close providers with `aclose()`. Tests block non-loopback network access; mock HTTP with `respx`. See `docs/providers.md`.
- TTS only through `byop/providers/tts` (`get_tts(...).synthesize(..., output_dir=...)`): output is always WAV 24 kHz mono 16-bit in a caller-owned dir. A provider's limits/formats/params live in its `ProviderQuirks` — never branch on the provider name elsewhere. A provider's accepted parameters (name, type, range) are `ParamSpec`s in its `ProviderQuirks`; speaker `voice_params` and previews are validated from them via `voice_param_problems`. Cross-field request errors use `services/validation.py` (`FieldValidationError` → 422 with FastAPI-shaped `loc`/`msg`). Kokoro (local, keyless) is the fallback default TTS: `services/defaults.py` picks the first configured paid provider, else Kokoro if its server answers. Use `anyio.Path` for file ops in async code (ruff ASYNC rules).
- Models (`byop/models/`, one module per aggregate; `columns.py` has the id/timestamp/`user_id` helpers): UUID `id`, tz-aware `created_at`/`updated_at`, `user_id` FK on every owned table. Enums are `StrEnum`s in `models/enums.py` stored as VARCHAR + CHECK via `enum_type()` (never free text, never native PG enums). Children of a show cascade at the DB level (`ondelete="CASCADE"` + `passive_deletes=True`); `usage_events` deliberately outlive shows/runs (SET NULL) so cost history survives.
- Migrations: autogenerate, then review by hand (no duplicate enum constraints, working `downgrade`). `tests/test_migrations.py` checks upgrade, no model drift and downgrade to base. Tests recreate the `byop_test` DB from migrations each session. The api container runs `alembic upgrade head` before starting; the admin user is seeded at startup from `BYOP_ADMIN_*` (never overwritten once it exists).

## TypeScript conventions
- `strict: true`; **no `any`** (use `unknown` + narrowing). Prefer `type` imports.
- Server state through TanStack Query only (no ad-hoc fetch in components); API calls go through `src/lib/api.ts`.
- Forms: react-hook-form + zod. Components are function components with explicit prop types.
- Lint with eslint, format with prettier; `npm run check` runs lint + typecheck + vitest + build. Tests live next to the code as `*.test.ts(x)`; shared test helpers in `src/test/`. Icons come from `react-icons/fi`; transient messages go through `useToast()` (`lib/toast.ts`, provided by the admin layout); per-resource query hooks live in `lib/<resource>.ts` (e.g. `lib/integrations.ts`); page components are default exports, routes in `src/routes.tsx`, sidebar/breadcrumb menu in `src/layout/menu.ts`.

## Testing expectations
- Every story adds tests for its new behaviour. API: pytest + pytest-asyncio against a real Postgres (transaction rollback per test); external HTTP is mocked with `respx`. Web: vitest + @testing-library/react.
- Do not call real paid APIs in tests. Assert behaviour, not implementation details.
- `make check` = lint + typecheck + tests for every part of the repo that exists. It must pass before each commit.

## Infra notes
`docker/nginx.conf` resolves `api` at request time (Docker resolver + variable `proxy_pass`) so recreating the api container never leaves the web proxy on a stale IP; keep that pattern for any new upstream.

## CI
`.github/workflows/ci.yml` runs on push and PR: `api` (installs ffmpeg, then ruff, mypy, pytest with postgres+redis services), `web` (eslint, tsc, vitest, build on Node 22), `compose` (repo checks + `docker compose build`). Keep it in step with `make check`; GitHub-hosted runners only.

## Commands
`make up|up-kokoro|down|logs|migrate|test|lint|typecheck|check|fmt` (`make help` lists them). `make up` creates `.env` from `.env.example` and generates `BYOP_SECRET_KEY` if empty; `docker-compose.override.yml` adds dev hot reload. `make test` (and `check`) first starts postgres/redis via compose (`make deps`); tests use the `byop_test` database from `TEST_DATABASE_URL`, created and migrated on demand. `make migrate` applies Alembic migrations. Local stack: `cp .env.example .env && make up`, then web on http://localhost:8080 (API under `/api`).

## Configuration
All configuration comes from environment variables documented in `.env.example` (single source of truth). Instance defaults for new shows come from `DEFAULT_LLM_PROVIDER`/`DEFAULT_LLM_MODEL`/`DEFAULT_SHOW_STYLE`. Settings fail fast with a readable `ConfigError` (e.g. missing `BYOP_SECRET_KEY`). Adding or changing a variable means updating `.env.example`, the README/docs and this file together.

## Commits
- Format: `<type>(<area>): <summary>` — types `feat|fix|chore|docs|test|refactor|ci`; areas like `api`, `web`, `infra`, `docs`, `providers`.
- Body ends with `Closes #N` (the story number) and the co-author trailer given by the task.
- Then `git push origin main`.

## Auth and multi-user
v0.1 is single-user: one admin seeded from `.env` (bcrypt hash in `users`). Login sets a signed JWT (`byop_session`, httpOnly, SameSite=Lax, Secure over https) valid `BYOP_SESSION_HOURS`; its `pv` claim fingerprints the password hash, so changing the password ends old sessions. Login is limited to 5/min per IP (Redis; keyed on the last `X-Forwarded-For` entry added by nginx; fails open if Redis is down).
- **Guard is the default**: in `byop/api/__init__.py` only `health` and `auth.public_router` are public; register every other router on the `protected` router (it depends on `current_user`). `tests/api/test_guard.py` enumerates the OpenAPI routes and fails if one answers an anonymous call with anything but 401 — add a route to its `PUBLIC_ROUTES` only for the RSS feed / episode audio and the like.
- Routers take `CurrentUser` (from `byop.api.deps`) and pass `user.id` to services, which filter every query by it.
- Web: `useMe`/`useLogin`/`useLogout` in `src/lib/auth.ts`, `RequireAuth` wraps the admin routes, and a 401 from any query clears the session so the guard redirects to `/login`.
- **Multi-user later**: the `users` table and `user_id` on every owned table already exist. Add an invite/signup flow (and per-user settings) that inserts `User` rows; `current_user`, services and tests already scope by `user_id`, so no schema change to owned tables is needed. `is_admin` gates instance-level settings.

## Open-source hygiene
This is a clean open-source project. Do not reference private or internal predecessor projects, organisations, domains or people in code, comments, docs or commits. Third-party code keeps its licence notice (e.g. Gradient Able, MIT).
