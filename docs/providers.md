# Model providers

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
| `kokoro` | `KokoroTTS` | `POST /v1/audio/speech` on a local Kokoro server | 4000 | `speed`, `lang_code`, `volume_multiplier`, `format` |

`format` is `pcm` (default) or `mp3`. Each provider's limits, formats, accepted
parameters and timeout are declared once, in its `ProviderQuirks`; unsupported
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
answers, else `null`. Adding a provider means one new subclass with its quirks plus a
line in `get_tts`; nothing else branches on the provider.

### Local voices with Kokoro (no API key)

The whole product can run without any paid key. The `kokoro` compose profile starts an
open-source [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) server (CPU image,
pinned by tag and digest in `docker-compose.yml`) that speaks the OpenAI speech API:

```sh
docker compose --profile kokoro up -d      # or: make up-kokoro
curl -b cookies.txt "http://localhost:8080/api/voices?provider=kokoro"
```

The api, worker and beat containers reach it at `http://kokoro:8880/v1`; set
`KOKORO_BASE_URL` (or `PUT /api/integrations/kokoro`) to use another server instead. The
first start downloads the model, so allow a minute before the health check passes, and CPU
synthesis is slower than a hosted API (the adapter's timeout is five minutes). `make down`
stops the profile too.

**GPU:** the compose file only ships the CPU image. For an NVIDIA GPU use the
`ghcr.io/remsky/kokoro-fastapi-gpu` image and a `deploy.resources.reservations.devices`
entry in a `docker-compose.override.yml`; no BYOP code changes are needed.
