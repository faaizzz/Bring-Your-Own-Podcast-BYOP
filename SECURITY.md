# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Report it privately through GitHub:
**Security › Report a vulnerability** on the
[repository](https://github.com/faaizzz/Bring-Your-Own-Podcast-BYOP/security/advisories/new). Include
what you found, how to reproduce it, and the version or commit you tested. You will get an answer
within a few days; we will keep you informed while we work on a fix and credit you in the release
notes if you wish.

## Supported versions

BYOP is pre-1.0. Security fixes go into the latest release and `main`; please update to the latest
version before reporting.

## What counts

In scope: anything that lets someone without a session reach data or actions that need one,
cross-user access, leaking or weakening the stored provider keys, server-side request forgery
through source URLs, injection, or a path to run code on the server.

Out of scope: problems that need a malicious admin, a compromised host or the `.env` file, denial of
service by an authenticated admin, and findings in the optional bundled services (Kokoro, RustFS,
Langfuse) that belong to those projects: report those upstream.

## How BYOP protects you

- **One login, signed sessions:** an `httpOnly`, `SameSite=Lax` cookie (`Secure` over https); changing
  the password ends old sessions; login attempts are rate-limited.
- **Guard by default:** every route needs a session except health, login, the podcast feed, episode
  audio and covers, and a test fails if another route is public.
- **Provider keys** you save in the app are encrypted with a key derived from `BYOP_SECRET_KEY`,
  masked in every response and redacted from logs ([docs/security.md](docs/security.md) covers
  rotating the key).
- **Server-side fetches** of URLs users type in refuse private and link-local addresses and are
  limited in size and time ([docs/sources.md](docs/sources.md)).
- **Secrets stay out of the repository:** `.env` is ignored and CI checks that no env file is tracked.

## Running it safely

- Change `BYOP_ADMIN_PASSWORD` before exposing the app, and set `PUBLIC_BASE_URL` to an https address
  behind a reverse proxy with a certificate ([docs/publishing.md](docs/publishing.md)).
- Keep `BYOP_SECRET_KEY` secret and backed up ([docs/backup.md](docs/backup.md)).
- Do not publish the Postgres or Redis ports (the development override binds them to loopback only).
- Keep images and dependencies up to date.
