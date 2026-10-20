# Model providers

## Configure from the UI

**Settings › Integrations** has one card per built-in provider (OpenRouter, OpenAI, ElevenLabs,
Kokoro, Langfuse) and, below them, your [OpenAI-compatible connections](#connections-any-openai-compatible-server). The badge shows where the credentials come from:
**Connected** (a key saved in the app), **From .env**, **Not configured**, or **Error**
(a failed connection test, or a stored key that can no longer be decrypted). *Configure* /
*Edit* opens a dialog that saves the override and tests it right away; *Test connection*
re-checks any configured provider, including ones set only in `.env`; *Remove override*
deletes the saved key so the `.env` value (if any) applies again. Saved keys are shown
masked and never sent back to the browser: leaving a key field blank keeps the stored one.

## Connections: any OpenAI-compatible server

A *connection* is an endpoint of your own that speaks the OpenAI API (`/v1`): Ollama, LM Studio,
vLLM, Groq, LiteLLM, a company gateway, a second Kokoro. Add as many as you like under
**Settings › Integrations › OpenAI-compatible connections**. Each has:

- a **name** (unique per account; it is what the pickers, the usage records and the costs show,
  as `conn:<name>`),
- a **base URL**, an optional **API key** and **custom headers** (name and value) sent on every
  request: chat, model list, speech and voice list. A key sets `Authorization`; a header of that
  name is used when there is no key. `Host`, `Content-Length`, `Transfer-Encoding` and
  `Connection` cannot be set. Keys and header values are stored encrypted, shown masked
  (`sk-…1234`) and never sent back; leave a value blank when editing to keep it,
- the **uses** it is for: language models, voices, web search (marks an endpoint whose models can search the web; source discovery
  will use it, see [sources](sources.md)), and an **enabled** switch.

*Test connection* lists the models and/or voices the connection is set up for. A server without
a list route (`GET /models`, `GET /audio/voices`) counts as reachable and the pickers then let
you type the model or voice id by hand. A connection that a show or speaker still uses cannot be
deleted, disabled, or switched off for that use (`409` naming what uses it).

Shows and speakers store `conn:<id>` in `llm_provider`, `tts_provider` and `fallback_tts_provider`
where a built-in name (`openai`, `kokoro`, ...) would go. Voice settings of a connection are
`model`, `speed`, `instructions`, `lang_code` and `volume_multiplier`; the server decides which
it understands. Costs: a model listed in the price table is priced as usual, anything else is
`unknown` (see [costs](costs.md)); set your own price under Settings › Pricing.

| Request | Purpose |
| --- | --- |
| `GET/POST /api/connections` | list / create (`name`, `base_url`, `api_key`, `headers: [{name, value}]`, `llm`, `tts`, `web_search`, `enabled`) |
| `GET/PATCH/DELETE /api/connections/{id}` | read / change (omitted fields and header values keep their stored value; `api_key: ""` removes the key; `headers` replaces the list) / delete |
| `POST /api/connections/{id}/test` | `{ok, detail, checks: [{capability, ok, detail}]}` |
| `GET /api/providers?capability=llm\|tts` | what a picker offers: built-in providers and connections as `{id, label, kind, configured, capabilities}` |

Upgrading from 0.1: an existing *OpenAI-compatible* integration becomes a connection named
"OpenAI-compatible" and the shows that used it point at it. If its key could not be read (a
changed `BYOP_SECRET_KEY`) it is created disabled with a placeholder URL for you to fix.

## Rate limits: wait between requests

Providers with low limits answer a busy run with HTTP 429. For each built-in provider (the
**Wait between requests (seconds)** field of its *Configure* dialog) and each connection (its
dialog), you can make BYOP wait 0–60 seconds (decimals allowed) between two requests; the card shows
*Waits N s between requests*. 0 means no wait, the default.

- It applies to every language-model request and every voice request of that provider: ranking,
  discovery, writing and revising scripts, each clip of the voice stage, voice previews. Listing
  models or voices is not delayed. A retry after a 429 waits too.
- The wait is shared: concurrent tasks and several workers queue up on one Redis key per user and
  provider (`throttle:<user>:<provider>` or `…:conn:<id>`, `services/throttle.py`), so two calls start
  at least N seconds apart however many run at once. If Redis is unavailable the request goes out
  without waiting, and a warning is logged.
- A wait of half a second or more is written to the run's log as *Waiting N s for the OpenRouter rate
  limit* (and to the structured log as `throttle_wait`), so a slow run explains itself.
- For a built-in provider the value belongs to your account, not to the key: set it alone (the
  dialog leaves a key from `.env` in use; `PUT /api/integrations/<provider>` with only
  `{"min_interval_s": 5}`) or together with a key. It is stored in `user_settings.request_intervals`.
  For a connection it is the connection's `min_interval_s` (`POST/PATCH /api/connections`).

Automatic back-off tuning and per-model limits are not part of this: the setting is one number
per provider.

## LLMs

Every LLM call goes through `byop.providers.llm.LLMProvider`:

```python
llm = get_llm(CredentialProvider.OPENROUTER, config)   # config from CredentialResolver
result = await llm.complete(
    [Message("system", "..."), Message("user", "...")],
    model="anthropic/claude-sonnet-4.5",
    response_schema=MyModel,            # optional: structured output
    temperature=0.7,
    metadata=CallMetadata(run_id=run_id, stage="script"),
)
result.parsed        # MyModel instance (when a schema was given)
result.text          # raw reply
result.usage         # TokenUsage(input_tokens, output_tokens), summed over repairs
result.cost_usd      # Decimal from OpenRouter, None elsewhere
result.latency_ms
```

| Provider | Class | Notes |
| --- | --- | --- |
| `openrouter` | `OpenRouterLLM` | requests `usage.include` so the response carries the real cost |
| `openai` | `OpenAICompatibleLLM` | `https://api.openai.com/v1`, or your proxy via a base URL |
| `conn:<id>` | `OpenAICompatibleLLM` | a [connection](#connections-any-openai-compatible-server): Ollama, LM Studio, vLLM, Groq, LiteLLM, a gateway |

Behaviour worth knowing:

- **Structured output** is requested with a JSON-schema `response_format`. Replies
  are parsed tolerantly (code fences and surrounding prose are fine) and validated
  with pydantic. An invalid reply gets exactly one repair round, in which the model
  sees its own answer and what was wrong with it; after that `LLMResponseError`
  is raised. If a server rejects `response_format` (HTTP 400) the schema is put in
  the prompt instead.
- **Errors** keep what the provider said: `LLMError` has `status_code`, `code` and `detail` (its
  own message, with anything key-like removed), and the message reads `request failed (HTTP 400):
  <the provider's reason>`.
- **Retries**: 429, 5xx and network errors are retried with exponential backoff,
  jitter and `Retry-After` (4 attempts, up to 30 s by default; `RetryPolicy`
  changes that). Other 4xx errors fail immediately. The request timeout is
  `timeout_s` (120 s by default).
- **Metadata** (`run_id`, `show_id`, `stage`) is logged with token counts, cost and
  latency for each call. Prompts and replies are never logged.

### Listing models

`GET /api/models?provider=openrouter|openai|conn:<id>` returns
`id`, `name`, `context_length` and prompt/completion prices (USD per million
tokens, where the provider publishes them). OpenRouter's list also carries what each model
accepts and produces (`supported_parameters`, `output_modalities`) and `web_search`: true when the
model searches the web by itself. The pickers show that as a "Web search" badge. Results are cached for an hour per
provider and credential. It answers `409` when the provider is not configured and
`502` when the provider cannot be reached.

### Using Ollama (or any local OpenAI-compatible server)

1. Run Ollama on the host (`ollama serve`) and pull a model (`ollama pull llama3.1`).
2. Add a connection with the base URL `http://host.docker.internal:11434/v1` (leave the key
   empty). With the API:

   ```sh
   curl -b cookies.txt -X POST http://localhost:8080/api/connections \
     -H 'content-type: application/json' \
     -d '{"name": "Ollama", "base_url": "http://host.docker.internal:11434/v1"}'
   curl -b cookies.txt -X POST http://localhost:8080/api/connections/<id>/test
   ```

3. Use the model name Ollama reports (for example `llama3.1`) when configuring a show.

`host.docker.internal` works on Docker Desktop, and the compose file maps it to the
host gateway on Linux. LM Studio works the same way (`http://host.docker.internal:1234/v1`).
Small local models follow JSON schemas less reliably, so expect more repair rounds.

## Text-to-speech

Every speech call goes through `byop.providers.tts.TTSProvider`:

```python
tts = get_tts(CredentialProvider.ELEVENLABS, config)
result = await tts.synthesize(
    "Welcome to the show.",
    voice_id="21m00Tcm4TlvDq8ikWAM",
    params={"stability": 0.4},          # the speaker's voice parameters
    output_dir=work_dir,                # caller-owned temp directory
    metadata=CallMetadata(run_id=run_id, stage="tts"),
)
result.audio_path     # <work_dir>/<id>.wav
result.sample_rate    # 24000
result.characters     # counted for every call
```

Whatever the provider returns (raw PCM, MP3, ...) is normalised to **WAV, 24 kHz,
mono, 16-bit**, so mixing never needs to know where audio came from. 24 kHz PCM is
wrapped in a WAV header directly; everything else is converted with ffmpeg. Audio is
streamed to disk in `output_dir`; nothing holds a whole file in memory, and no
temporary files are left behind on failure.

| Provider | Class | Endpoint | Max chars | Parameters (`params`) |
| --- | --- | --- | --- | --- |
| `openai` | `OpenAITTS` | `POST /audio/speech` | 4096 | `model`, `speed`, `instructions`, `format` |
| `elevenlabs` | `ElevenLabsTTS` | `POST /v1/text-to-speech/{voice_id}` | 5000 | `model_id`, `stability`, `similarity_boost`, `style`, `speed`, `use_speaker_boost`, `language_code`, `seed`, `format` |
| `openrouter` | `OpenRouterTTS` | `POST /audio/speech` on OpenRouter | 4096 | `model` (required), `speed`, `instructions`, `format` |
| `kokoro` | `KokoroTTS` | `POST /v1/audio/speech` on a local Kokoro server | 800 | `speed`, `lang_code`, `volume_multiplier`, `format` |

`format` is `pcm` (default) or `mp3`. Each provider's limits, formats, accepted
parameters (with type and range, `ParamSpec`) and timeout are declared once, in its `ProviderQuirks`; unsupported
parameters or over-long text raise `TTSParamError` before any request is sent
(splitting long scripts is the synthesis stage's job). Failures raise `TTSError`;
429, 5xx and network errors are retried like LLM calls.

`GET /api/voices?provider=openai|elevenlabs|openrouter|kokoro` (or `conn:<id>`; `model=` for providers whose voices follow the model) returns `id`, `name`,
`language`, `gender` and `preview_url`, cached for an hour per credential. OpenAI
and OpenRouter have no voice-listing endpoint, so their built-in voice names are
listed statically; Kokoro's come from the server and are decoded from their ids
(`af_bella` = American English, female). Without `provider` the default one is used,
and `GET /api/voices/default-provider` tells the UI which to preselect: the first
configured paid provider (ElevenLabs, OpenAI, OpenRouter), else Kokoro when its server
answers, else `null`.

### Voice models

A speaker on OpenRouter, OpenAI, ElevenLabs or a connection picks the **speech model** in a
searchable *Voice model* list between *Voice provider* and *Voice* (it is the `model` or
`model_id` voice setting, no longer a field under *Voice settings*). It is required for OpenRouter
(the speaker cannot be saved without one, in the form or through the API), optional elsewhere,
where the list shows the provider's default. A model that is not in the list, such as one a
speaker already had, can be typed and is kept.

`GET /api/voices/models?provider=…` returns `{param, required, default, voices_follow_model,
models: [{id, name, description}]}`, cached for an hour per credential:

| Provider | Models | Notes |
| --- | --- | --- |
| `openrouter` | `GET /models?output_modalities=speech` (OpenRouter keeps speech models out of its default list; the modality is `speech`, not `audio`); a short built-in list if it returns none | each model lists the voices it offers, so `GET /api/voices?provider=openrouter&model=…` returns those (OpenAI's names when it lists none) |
| `openai` | the known speech models (`gpt-4o-mini-tts`, `tts-1`, `tts-1-hd`) | default `gpt-4o-mini-tts` |
| `elevenlabs` | `GET /v1/models`, the ones that can do text to speech | default `eleven_multilingual_v2` |
| connection | `GET /models` of the server | a server without it gives an empty list and the model is typed |
| `kokoro` | none (`param` is null, no list is shown) | |

The preview (`POST /api/voices/preview`) and synthesis use the chosen model, since it is part of the
speaker's `voice_params`. Speaker voice settings are validated from the same declarations (`voice_param_problems`) and clips can be auditioned with `POST /api/voices/preview` (see [shows](shows.md#voice-preview)). Adding a provider means one new subclass with its quirks plus a
line in `get_tts`; nothing else branches on the provider.

### Local voices with Kokoro (no API key)

The whole product can run without any paid key. The `kokoro` compose profile starts an
open-source [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) server (CPU image,
pinned by tag and digest in `docker-compose.yml`) that speaks the OpenAI speech API:

```sh
make up-kokoro                             # or: make up-full, or: docker compose --profile kokoro up -d
curl -b cookies.txt "http://localhost:8080/api/voices?provider=kokoro"
```

The api, worker and beat containers reach it at `http://kokoro:8880/v1` (`make up-kokoro` and
`make up-full` set that; with plain `docker compose --profile kokoro` put it in `KOKORO_BASE_URL`).
A minimal `make up` has no Kokoro, so it is not offered as a voice provider. Set
`KOKORO_BASE_URL` (or `PUT /api/integrations/kokoro`) to use another server instead. The
first start downloads the model, so allow a minute before the health check passes, and CPU
synthesis is slower than a hosted API (the adapter's timeout is five minutes). `make down`
stops the profile too.

**GPU:** the compose file only ships the CPU image. For an NVIDIA GPU use the
`ghcr.io/remsky/kokoro-fastapi-gpu` image and a `deploy.resources.reservations.devices`
entry in a `docker-compose.override.yml`; no BYOP code changes are needed.

## Zero-cost mode: Kokoro voices and a local model

You can run BYOP without paying anyone: Kokoro for voices and [Ollama](https://ollama.com) (or LM
Studio, vLLM, ...) for the language model.

1. `make up-kokoro` (or `make up-full`) starts BYOP with the local Kokoro server; it is preselected
   as the voice provider whenever no paid voice key exists.
2. Run Ollama on your machine and pull a model that follows JSON instructions well (a 7-14B
   instruction model is a sensible minimum): `ollama pull qwen2.5:14b`.
3. Settings › Integrations › **Add connection**: base URL `http://host.docker.internal:11434/v1`
   (the compose file makes that name work on Linux and Docker Desktop), no key.
4. Create a show, choose your connection as the language model provider and pick its model.

Expect it to be slower than hosted models (a few minutes for the script, several for voices on a
CPU), and small models sometimes need a second try; the script writer re-asks once when its
output is unusable, and the run's log says what happened. Discovery of sources needs a model that
can search the web, so add feeds by hand.

## Feature matrix

| | OpenRouter | OpenAI | ElevenLabs | Kokoro | Connection |
| --- | :-: | :-: | :-: | :-: | :-: |
| Language models (scripts, ranking) | yes | yes | | | yes |
| Web search for source discovery | yes (`:online`) | with a search-capable model | | | model-dependent |
| Voices | yes | yes | yes | yes (local, free) | if the server has `/audio/speech` |
| Cost reported by the provider | yes | | | | |
| Cost from the price table ([costs](costs.md)) | | yes | yes | yes (free) | |
| Needs an API key | yes | yes | yes | no | usually not |

Langfuse ([tracing](langfuse.md)) and S3 storage ([storage](storage.md)) are optional add-ons.

## Adding a provider

A new language-model or voice service is one small adapter plus a few registrations. Follow the
existing adapters; every step has a test next to it.

### A language model (an OpenAI-style API)

Most services speak the OpenAI chat API; for those a subclass is a dozen lines.

1. **Name it.** Add a value to `CredentialProvider` (`byop/models/enums.py`) and an Alembic
   migration that widens the `provider` CHECK constraint of `provider_credentials` (see migration
   `0007` for how a constraint is replaced). Add the name to the `LLMProviderName` literals in
   `byop/schemas/` and `LLM_PROVIDERS` in `apps/web/src/lib/voices.ts`.
2. **Write the adapter**, `byop/providers/llm/<name>.py`, by subclassing `OpenAIChatProvider`
   (see `openrouter.py`): set `name`, the default base URL, any extra headers or request body
   fields, and `reports_cost = True` if responses carry a cost. A service with another protocol
   implements `LLMProvider` (`complete`, `list_models`, `aclose`) and must call `record_usage`
   after each call so costs and traces work ([costs](costs.md)).
3. **Register it** in `get_llm` and `LLM_PROVIDERS` (`byop/providers/llm/__init__.py`).
4. **Credentials.** If it has an environment variable, add the setting to `byop/config.py`, a branch
   to `_env_config` in `services/credentials.py`, the variable to `.env.example` and
   [configuration](configuration.md). Add its connection probe to `services/integration_check.py`.
5. **UI.** Add its card to `PROVIDERS` in `apps/web/src/lib/integrations.ts`.
6. **Prices.** Add models you know to `byop/pricing.yaml` if the service does not report cost.
7. **Tests.** Mock the HTTP with `respx` (never call a real API): copy `tests/providers/llm/test_llm.py`
   and cover a plain call, a structured call, a retry, an error, and the usage report.

### A voice

1. **Name it** as above (`CredentialProvider` + migration) and add it to `TTS_PROVIDERS`.
2. **Write the adapter**, `byop/providers/tts/<name>_tts.py`: subclass `TTSProvider` and fill in
   `name` and `quirks`, a `ProviderQuirks` declaring everything that differs (maximum characters per
   request, the audio formats it can return and the default, the accepted voice `params` with a
   `ParamSpec` each, the timeout, and `max_concurrency` for servers that handle one request at a
   time). Implement `build_request` (URL, JSON, headers), `auth_headers` and `list_voices`. The base
   class does retries, streaming to disk, conversion to the canonical WAV and the usage report.
   Nothing outside the adapter may branch on the provider name.
3. **Register it** in `_CLASSES`, `TTS_PROVIDERS` and `get_tts` (`byop/providers/tts/__init__.py`).
4. **Credentials, UI and prices** as above; also add its voice parameters to `VOICE_PARAMS` in
   `apps/web/src/pages/shows/form/schema.ts`, which must stay in step with the `ParamSpec`s, and its
   price per million characters to `pricing.yaml`.
5. **Tests:** add it to the `CASES` of `tests/providers/tts/test_providers.py`, which already checks
   normalisation, limits, retries and usage for every provider, and to `test_param_specs.py`.

Run `make check` and a real generation with the new provider before opening the pull request.
