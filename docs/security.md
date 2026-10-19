# Secrets and key rotation

## Where provider keys come from

For every built-in provider (OpenRouter, OpenAI, ElevenLabs, Langfuse, Kokoro) BYOP uses, in
order:

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

`provider` is one of `openrouter`, `openai`, `elevenlabs`, `langfuse`, `kokoro`. Every call needs
a signed-in session.

OpenAI-compatible servers are *connections* (`/api/connections`, see [providers](providers.md)).
Their key and custom header values are encrypted the same way, are masked in every response, are
never logged, and are re-encrypted by `rotate-key` too.

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

## Hardening of the web tier

`docker/nginx.conf` is the only thing exposed to the network and sets:

- **Security headers** on every response: a `Content-Security-Policy` that allows only this origin
  (scripts, styles, fonts, images, audio and API calls; no framing, no plugins),
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, a `Referrer-Policy`, a
  `Permissions-Policy` that turns off camera, microphone and location, and
  `Strict-Transport-Security` when the request arrived over https (a proxy in front must send
  `X-Forwarded-Proto: https`). The server version is hidden.
- **Request size limits:** 1 MB for ordinary requests; only the cover and the intro/outro/music
  uploads may be larger (up to 26 MB), and the API enforces its own per-file limits too (covers
  10 MB, audio 25 MB, answered with `413`).
- **Same origin only:** the API sends no CORS headers, so browsers refuse cross-origin use of it.
  The session cookie is `httpOnly` and `SameSite=Lax`.

## Rate limits

- Login: 5 attempts a minute per client address.
- Public feed: `PUBLIC_FEED_RATE_PER_MINUTE` (120) and episode audio:
  `PUBLIC_MEDIA_RATE_PER_MINUTE` (600) requests a minute per client address; over the limit the
  answer is `429` with a `Retry-After` header. Podcast apps that share an address (a crawler farm)
  can be given more room by raising the numbers, or `0` switches a limit off.

The client address is the last `X-Forwarded-For` entry that nginx appends, so a visitor cannot
choose it. Counters live in Redis; if Redis is down the limits are skipped (fail open) rather than
locking you out.

## Dependencies

`pip-audit` and `npm audit` run in CI on every push and weekly ([releasing](releasing.md)); the
images are rebuilt on every release.
