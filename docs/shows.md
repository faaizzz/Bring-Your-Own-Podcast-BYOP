# Shows API

A show is one podcast: its topic, language, style, model, schedule and feed
metadata. All routes need a session; every query is scoped to the signed-in user, so
another user's show is a `404`.

| Method | Path | |
| --- | --- | --- |
| `GET` | `/api/shows` | List, newest first, with `episode_count`, `last_run_status`, `next_run_at` |
| `POST` | `/api/shows` | Create (`title` and `topic` are required) |
| `GET` | `/api/shows/{id}` | One show |
| `PATCH` | `/api/shows/{id}` | Change only the fields you send; `null` clears optional ones |
| `DELETE` | `/api/shows/{id}` | Delete the show, its episodes/runs/items/sources/speakers and its media files |

## Rules

- **Slug**: generated from the title (`Daily AI News` → `daily-ai-news`, then `-2`, `-3`
  on a clash) or sent explicitly. Slugs are unique across the instance because they appear
  in public feed URLs. Changing the title never changes the slug. The slug can be edited
  until the first episode is published; after that (`slug_locked: true`) a change is a
  `409`, so subscribers' feed URLs stay valid.
- **Validation**: `language` is a BCP-47 tag (`en`, `pt-BR`, `zh-Hans-CN`);
  `target_minutes` 1–60; `items_per_episode` 1–20; `timezone` an IANA name; a
  `daily`/`weekly`/`monthly` schedule needs `schedule_time` (plus `schedule_weekday`
  0–6 for weekly, `schedule_monthday` 1–31 for monthly).
- **Model**: `llm_provider` (`openrouter`, `openai`, `openai_compatible`) and `llm_model`
  are set together. The model must appear in the provider's model list (the cached
  `/api/models` list). If the provider is not configured or its list cannot be fetched,
  the show is still saved and the response carries a note in `warnings`.
- **Defaults** for omitted fields come from the instance: `DEFAULT_LLM_PROVIDER` +
  `DEFAULT_LLM_MODEL` (used only as a pair) and `DEFAULT_SHOW_STYLE` (see `.env.example`).
- **Schedule fields** are stored as sent; `next_run_at` is computed by the scheduler
  and is read-only here.

## Media

Everything a show owns lives under the storage prefix `shows/<show id>/` (below
`MEDIA_ROOT` for local storage). Deleting a show removes the database rows first and
then that prefix; a cleanup failure is logged but does not fail the request.
