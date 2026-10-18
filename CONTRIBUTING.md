# Contributing

Thanks for helping make BYOP better! This guide gets you from a fresh clone to a pull request.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report security
problems privately, as described in [SECURITY.md](SECURITY.md), not in a public issue.

## Ways to help

- **Report a bug or suggest a feature** with an issue (the templates ask for what is needed).
- **Improve the docs:** if something confused you, it confuses others.
- **Add a provider:** [docs/providers.md](docs/providers.md#adding-a-provider) is a step-by-step guide.
- **Pick up an issue.** Ask in the issue first for anything bigger than a small fix, so we agree on
  the approach before you spend time on it.

## Set up

You need Docker (with compose), [uv](https://docs.astral.sh/uv/) for Python 3.12, Node 22 and ffmpeg.

```sh
git clone <your fork> && cd Bring-Your-Own-Podcast-BYOP
make up                 # the full stack on http://localhost:8080 (API hot-reloads)
make check              # lint + types + tests for api and web
```

- API: `cd apps/api && uv run pytest -q` (needs Postgres and Redis; `make test` starts them for you).
- Web: `cd apps/web && npm ci && npm run dev` (proxies `/api` to a running API), `npm run check` for
  lint, types, tests and build.
- Browser test: `make e2e` runs the whole product against mock model and voice servers
  ([docs/e2e.md](docs/e2e.md)).

`make help` lists every target. `.env.example` documents every setting
([docs/configuration.md](docs/configuration.md)).

## Where things are

[docs/architecture.md](docs/architecture.md) shows the services and the pipeline;
[CLAUDE.md](CLAUDE.md) is the contract for the code: layout, conventions (async everywhere,
thin routers, services filter by `user_id`, money is `Decimal`, no `any` in TypeScript, ...) and the
details of each subsystem. Read the part for the area you touch.

## Making a change

1. Keep it focused: one change per pull request, and nothing that is not needed for it.
2. Write tests for new behaviour: API tests run against a real Postgres, external HTTP is mocked with
   `respx` (tests must never call paid APIs), web tests use vitest and Testing Library. Never weaken
   or skip a test to make it pass.
3. Update the docs, `.env.example` and CLAUDE.md when you change behaviour, a variable or a
   convention (`make check` verifies that every variable in `.env.example` is documented).
4. Run `make check` before you push. For changes to the pipeline, the feed or the UI flow, also run
   `make e2e`.
5. Database changes need an Alembic migration: autogenerate, then review it by hand (no duplicate
   constraints, a working `downgrade`); `tests/test_migrations.py` checks upgrade, drift and
   downgrade.

## Commits and pull requests

Commit messages follow `<type>(<area>): <summary>`: types `feat`, `fix`, `chore`, `docs`, `test`,
`refactor`, `ci`; areas such as `api`, `web`, `infra`, `docs`, `providers`. Example:
`feat(api): add shows CRUD`. Mention the issue it closes (`Closes #12`).

Open the pull request against `main`; CI runs lint, types, tests and a build of the images (and
the end-to-end test on `main`). Describe what changed and how you checked it. Be patient and kind in
review: everyone here is a volunteer.

## Licence

By contributing you agree that your work is released under the project's [MIT licence](LICENSE).
Third-party code keeps its own licence notice (for example the Gradient Able theme).
