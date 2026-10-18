# Secrets and key rotation

## Where provider keys come from

For every provider (OpenRouter, OpenAI, ElevenLabs, Langfuse, Kokoro,
OpenAI-compatible) BYOP uses, in order:

1. the override you saved under **Settings › Integrations** (stored encrypted),
2. the matching variable in `.env` (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`,
   `ELEVENLABS_API_KEY`, `LANGFUSE_*`, `KOKORO_BASE_URL`),
3. otherwise the provider is "not configured".

Overrides are encrypted with Fernet, using a key derived from `BYOP_SECRET_KEY`.
The API never returns a stored secret: it shows a masked value such as `sk-…1234`
and where it came from (`user`, `env` or `none`). Logs redact secret-looking
fields and values.

## API

| Request | Purpose |
| --- | --- |
| `GET /api/integrations/{provider}` | effective configuration, masked |
| `PUT /api/integrations/{provider}` | save an override (`api_key`, `base_url`, `extra`, `enabled`); omitted fields keep their stored value |
| `DELETE /api/integrations/{provider}` | remove the override, falling back to `.env` |
| `POST /api/integrations/{provider}/test` | cheap live call; returns `{ "ok": bool, "detail": "..." }` |

`provider` is one of `openrouter`, `openai`, `elevenlabs`, `langfuse`, `kokoro`,
`openai_compatible`. Every call needs a signed-in session.

## Rotating `BYOP_SECRET_KEY`

Changing the key makes existing overrides unreadable (and signs everyone out),
so re-encrypt them with the previous key first:

```sh
# 1. Put the NEW key in .env as BYOP_SECRET_KEY (generate one: openssl rand -hex 32).
# 2. Re-encrypt, passing the OLD key:
docker compose run --rm -e OLD_BYOP_SECRET_KEY='<previous key>' api \
  python -m byop.cli rotate-key
# 3. Restart so every service picks up the new key:
docker compose up -d --force-recreate
```

The command is all-or-nothing: if any stored secret cannot be decrypted with the
old key, nothing is changed and it exits non-zero. If you lost the old key,
delete the overrides and enter them again (or rely on `.env`).
