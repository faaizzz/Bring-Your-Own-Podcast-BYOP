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
| `POST` | `/api/shows/{id}/pause` | Stop the schedule (manual runs still work); `next_run_at` becomes `null` |
| `POST` | `/api/shows/{id}/resume` | Resume it; the next run is the first slot after now |
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
- **Model**: `llm_provider` (`openrouter`, `openai`, or `conn:<id>` of an [OpenAI-compatible connection](providers.md#connections-any-openai-compatible-server)) and `llm_model`
  are set together. The model must appear in the provider's model list (the cached
  `/api/models` list). If the provider is not configured or its list cannot be fetched,
  the show is still saved and the response carries a note in `warnings`.
- **Defaults** for omitted fields come from the instance: `DEFAULT_LLM_PROVIDER` +
  `DEFAULT_LLM_MODEL` (used only as a pair) and `DEFAULT_SHOW_STYLE` (see `.env.example`).
- **`ranking_hints`** (optional, up to 2000 characters) tells the editor model which stories to
  favour; see [choosing stories](ranking.md).
- **Schedule fields** are stored as sent; `next_run_at` is computed from them (read-only) and
  recomputed whenever the schedule, the time zone or `paused` changes ([scheduling](scheduling.md)).

## Styles

**Settings › Styles** lists the four built-in styles with the exact instructions each gives the
model (read-only), and your own. *Duplicate* copies any style (built-in or yours) into a new one you
can edit; *Add style* starts from nothing. A show picks a style in its Topic step (grouped Built-in /
Custom, with a preview of the instructions and a *Manage styles* link); the overview shows its name.

| Method and path | Purpose |
| --- | --- |
| `GET /api/styles` | the built-ins (`kind: builtin`, `id` is the key such as `conversational`, with their `instructions`) then yours (`kind: custom`, UUID `id`); `shows_using` counts the shows |
| `POST /api/styles` | create `{name, description?, instructions}`; names are unique per user (`409`); instructions that do not render are a `422` |
| `PATCH /api/styles/{id}`, `DELETE /api/styles/{id}` | change / delete one of yours; deleting a style that shows use is a `409` that names them |

A show sends `style` (a built-in key) **or** `custom_style_id` (not both, `422`); choosing a built-in
style clears `custom_style_id`, and `custom_style_id: null` goes back to the built-in `style`. The
database refuses to delete a style that a show uses (`ON DELETE RESTRICT`). How the instructions
reach the model is in [scripts](scripts.md#styles). Existing shows keep their built-in style.

## Scheduling

Schedules (`schedule_kind`, `schedule_time`, `timezone`, pause/resume) are described in
[scheduling](scheduling.md).

## In the app

**Shows** lists one card per show (placeholder cover, schedule badge, last episode, next
run); an empty list offers *Create your first show*. **New show** is a five-step wizard:
Topic, Speakers & voices (1–4 speakers with searchable voice pickers, an inline preview
player, a *Voice model* list for providers with a choice of speech model, per-provider voice settings and an optional fallback voice), Models (provider and
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

## Persona library

**Settings › Personas** keeps personas you reuse: a name, the persona text, and optionally a default
voice (provider, voice, and a voice model where the provider has one). Every user starts with five
you can edit or delete (curious host, expert analyst, friendly sceptic, storyteller, plain-language
explainer): they are added when the user is created, and by the upgrade to existing users once.

In a show's **Speakers** step, *From library* copies a persona into the speaker: its text, and its
voice when that voice provider is set up (otherwise you are told it was left out). *Save to library*
keeps the speaker's persona, and its voice with settings, as a new persona. Both are copies:
speakers never point back at the library, so editing or deleting a persona changes no show.

| Method and path | Purpose |
| --- | --- |
| `GET /api/personas` | your personas by name |
| `POST /api/personas` | create `{name, persona, tts_provider?, voice_id?, voice_params?}`; names are unique per user (`409`); a voice needs a provider and a voice together and valid settings (`422`) |
| `PATCH /api/personas/{id}`, `DELETE /api/personas/{id}` | change (omitted fields keep their value; `tts_provider` and `voice_id` set to null remove the voice) / delete |

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
