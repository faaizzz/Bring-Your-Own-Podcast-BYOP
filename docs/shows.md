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

## In the app

**Shows** lists one card per show (placeholder cover, schedule badge, last episode, next
run); an empty list offers *Create your first show*. **New show** is a five-step wizard:
Topic, Speakers & voices (1–4 speakers with searchable voice pickers, an inline preview
player, per-provider voice settings and an optional fallback voice), Models (provider and
model with the price per 1M tokens), Schedule, Review. A show opens at `/shows/<id>` with the
tabs Overview, Sources, Episodes, Runs and Settings (Sources, Episodes and Runs are
placeholders until those features land). *Settings* edits the same four steps as sections
and holds *Delete show*. Client-side validation mirrors the API's rules; any 422 from the API
is shown on the matching field and opens its step. `GET /api/voices/default-speakers` gives
the wizard the two hosts it starts with.

## Speakers

Each show has 1–4 speakers; the order is the speaking order. New shows start with two
hosts (Alex and Sam) on the default TTS provider: the first configured paid provider,
else Kokoro (see [providers](providers.md#text-to-speech)).

| Method | Path | |
| --- | --- | --- |
| `GET` | `/api/shows/{id}/speakers` | The ordered list |
| `PUT` | `/api/shows/{id}/speakers` | Replace the whole list (a JSON array of 1–4 speakers) |

A speaker has `name` (unique within the show, case-insensitive), `persona` (role and
speaking style given to the script writer), `tts_provider` (`openai`, `elevenlabs`,
`openrouter`, `kokoro`), `voice_id`, `voice_params`, and an optional fallback pair
`fallback_tts_provider` + `fallback_voice_id` used if the main provider fails.

`voice_params` are checked against the provider's declared parameters (name, type and
range, e.g. OpenAI `speed` 0.25–4, ElevenLabs `stability` 0–1, OpenRouter requires
`model`). A fallback carries no parameters, so a provider that requires one (OpenRouter)
cannot be a fallback. Problems come back as `422` with one entry per field, located like
FastAPI's own errors, e.g. `{"loc": ["body", 1, "voice_params", "speed"], "msg": "must be at most 4"}`.
Replacing keeps the ids of speakers that stay in the same position.

## Voice preview

`POST /api/voices/preview` with `{"provider", "voice_id", "params"?, "text"?}` returns a
short `audio/mpeg` clip (the default sentence, or up to 300 characters of `text`). Clips
are cached in media storage under `previews/<sha256>.mp3`, keyed by provider, voice,
parameters and text, so repeating a request costs nothing. Parameters are validated like
speaker `voice_params`.

```sh
curl -b cookies.txt -H 'content-type: application/json' -o preview.mp3 \
  -d '{"provider":"kokoro","voice_id":"af_bella","params":{"speed":1.1}}' \
  http://localhost:8080/api/voices/preview
```

## Cover image

`POST /api/shows/{id}/cover` uploads a PNG/JPEG, `DELETE` removes it, and `cover_url` on the show
links the public image. See [storage](storage.md#covers) for the processing rules.
The wizard's first step has a cover picker (uploaded right after the show is created) and the
Settings tab replaces or removes it immediately.

## Media

Everything a show owns lives under the storage prefix `shows/<show id>/` (below
`MEDIA_ROOT` for local storage, or in the S3 bucket). Deleting a show removes the database rows first and
then that prefix; a cleanup failure is logged but does not fail the request.
