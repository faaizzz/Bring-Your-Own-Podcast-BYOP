# Model providers

## Configure from the UI

**Settings › Integrations** has one card per provider (OpenRouter, OpenAI, ElevenLabs,
Kokoro, OpenAI-compatible, Langfuse). The badge shows where the credentials come from:
**Connected** (a key saved in the app), **From .env**, **Not configured**, or **Error**
(a failed connection test, or a stored key that can no longer be decrypted). *Configure* /
*Edit* opens a dialog that saves the override and tests it right away; *Test connection*
re-checks any configured provider, including ones set only in `.env`; *Remove override*
deletes the saved key so the `.env` value (if any) applies again. Saved keys are shown
masked and never sent back to the browser: leaving a key field blank keeps the stored one.

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
| `openai_compatible` | `OpenAICompatibleLLM` | any OpenAI-style server: Ollama, LM Studio, vLLM, LiteLLM |

Behaviour worth knowing:

- **Structured output** is requested with a JSON-schema `response_format`. Replies
  are parsed tolerantly (code fences and surrounding prose are fine) and validated
  with pydantic. An invalid reply gets exactly one repair round, in which the model
  sees its own answer and what was wrong with it; after that `LLMResponseError`
  is raised. If a server rejects `response_format` (HTTP 400) the schema is put in
  the prompt instead.
- **Retries**: 429, 5xx and network errors are retried with exponential backoff,
  jitter and `Retry-After` (4 attempts, up to 30 s by default; `RetryPolicy`
  changes that). Other 4xx errors fail immediately. The request timeout is
  `timeout_s` (120 s by default).
- **Metadata** (`run_id`, `show_id`, `stage`) is logged with token counts, cost and
  latency for each call. Prompts and replies are never logged.

### Listing models

`GET /api/models?provider=openrouter|openai|openai_compatible` returns
`id`, `name`, `context_length` and prompt/completion prices (USD per million
tokens, where the provider publishes them). Results are cached for an hour per
provider and credential. It answers `409` when the provider is not configured and
`502` when the provider cannot be reached.

### Using Ollama (or any local OpenAI-compatible server)

1. Run Ollama on the host (`ollama serve`) and pull a model (`ollama pull llama3.1`).
2. Add an `openai_compatible` integration with the base URL
   `http://host.docker.internal:11434/v1` (leave the key empty). With the API:

   ```sh
   curl -b cookies.txt -X PUT http://localhost:8080/api/integrations/openai_compatible \
     -H 'content-type: application/json' \
     -d '{"base_url": "http://host.docker.internal:11434/v1"}'
   curl -b cookies.txt -X POST http://localhost:8080/api/integrations/openai_compatible/test
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

`GET /api/voices?provider=openai|elevenlabs|openrouter|kokoro` returns `id`, `name`,
`language`, `gender` and `preview_url`, cached for an hour per credential. OpenAI
and OpenRouter have no voice-listing endpoint, so their built-in voice names are
listed statically; Kokoro's come from the server and are decoded from their ids
(`af_bella` = American English, female). Without `provider` the default one is used,
and `GET /api/voices/default-provider` tells the UI which to preselect: the first
configured paid provider (ElevenLabs, OpenAI, OpenRouter), else Kokoro when its server
answers, else `null`. Speaker voice settings are validated from the same declarations (`voice_param_problems`) and clips can be auditioned with `POST /api/voices/preview` (see [shows](shows.md#voice-preview)). Adding a provider means one new subclass with its quirks plus a
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
3. Settings › Integrations › **OpenAI-compatible**: base URL `http://host.docker.internal:11434/v1`
   (the compose file makes that name work on Linux and Docker Desktop), no key.
4. Create a show, choose the *OpenAI-compatible* provider and your model.

Expect it to be slower than hosted models (a few minutes for the script, several for voices on a
CPU), and small models sometimes need a second try; the script writer re-asks once when its
output is unusable, and the run's log says what happened. Discovery of sources needs a model that
can search the web, so add feeds by hand.

## Feature matrix

| | OpenRouter | OpenAI | ElevenLabs | Kokoro | OpenAI-compatible |
| --- | :-: | :-: | :-: | :-: | :-: |
| Language models (scripts, ranking) | yes | yes | | | yes |
| Web search for source discovery | yes (`:online`) | with a search-capable model | | | model-dependent |
| Voices | yes | yes | yes | yes (local, free) | |
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
