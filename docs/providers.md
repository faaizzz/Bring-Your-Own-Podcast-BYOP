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
