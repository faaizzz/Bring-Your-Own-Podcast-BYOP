# Sources

A source is somewhere a show gets its stories from. Each show has any number of them,
managed under the show's **Sources** tab or through `/api/shows/{id}/sources`.

| Kind | Value | Checked when added |
| --- | --- | --- |
| `rss` | URL of an RSS, Atom or RDF feed | The feed is fetched and parsed; an unusable feed is rejected with the reason |
| `url` | URL of a page to watch | Only the address is vetted (see below); nothing is fetched yet |
| `web_search` | A search query (up to 500 characters), answered at run time by a language model with web search | Nothing |

A source also has an optional `name` (an RSS feed defaults to its own title), `enabled`,
`origin` (`user`, or `discovered` for sources found automatically), `last_fetched_at`
and `last_error`. The last two are filled in when stories are collected. The `kind` of a
source cannot be changed; delete it and add another.

| Method | Path | |
| --- | --- | --- |
| `GET` | `/api/shows/{id}/sources` | List |
| `POST` | `/api/shows/{id}/sources` | Add (`201`; `409` if the same kind and value is already there) |
| `POST` | `/api/shows/{id}/sources/validate` | Fetch an RSS feed *without saving*: `{ok, title, entry_count, latest_titles, detail}` |
| `PATCH` | `/api/shows/{id}/sources/{sid}` | Change `name`, `enabled` or `value` (a new feed URL is validated again and clears the old fetch history) |
| `DELETE` | `/api/shows/{id}/sources/{sid}` | Remove |

Validation problems come back as `422` located at `body.value`, for example *The URL returns a
web page, not an RSS or Atom feed*, *The server answered HTTP 404*, *The server took too long
to answer*. `/validate` reports the same reasons as `{"ok": false, "detail": ...}` with status
`200`, because for a "try this URL" button a bad feed is an answer.

## What the server will fetch

Source URLs are typed in by users and fetched by the server, so they are checked
(`byop/services/safe_http.py`):

- only `http` and `https`, without credentials in the URL;
- the host must resolve to a **public** address. Loopback, private ranges (10/8, 172.16/12,
  192.168/16, ...), carrier-grade NAT and IPv6 unique-local addresses are refused, and
  link-local (including the cloud metadata address 169.254.169.254), unspecified and
  multicast addresses are **always** refused;
- up to 5 redirects, each hop checked the same way;
- 15 seconds and 5 MB per fetch; no proxies from the environment.

To use a feed on your own network (a self-hosted RSS bridge, say) set
`SOURCES_ALLOW_PRIVATE_NETWORKS=true` in `.env`. That allows private and loopback addresses;
link-local and metadata addresses stay blocked. The address is checked when the request is
made, which is a guard against mistakes and the obvious attacks, not a sandbox against a hostile
DNS server.

## In the app

The table shows type, name, address, origin, an enabled switch (saved immediately), last fetch
and last error, with edit and remove actions. *Add source* opens a dialog; for an RSS feed
*Validate feed* shows its title, entry count and the three latest titles before you add it.

## Discovering sources

Given only a topic, BYOP can propose sources. In the app: **Discover sources** on the Sources
tab, or the *Sources* step of the create wizard (nothing is saved until the show is created).

How it works (`byop/services/discovery.py`, run by the Celery worker):

1. A language model with web search is asked for RSS feeds, pages to watch and search queries
   for the topic, in the show's language, as structured JSON. On OpenRouter `:online` is appended
   to the model id so it can search the web (`perplexity/…` models, which search natively, and ids
   already ending in `:online` are left alone). On other providers the configured model is
   used as is, so pick one that can search (see *Can the model search?* below).
2. Every candidate is **checked**: an RSS feed must be fetchable, parse, have entries and (when
   its entries carry dates) a newest one under 90 days old; a page must be fetchable. The same
   address rules as for manual sources apply. Failures are dropped; sources the show already has
   are left out.
3. One to three `web_search` queries are always proposed (a baseline is made from the topic if the
   model gave none).

The model is chosen as: `DISCOVERY_LLM_PROVIDER` + `DISCOVERY_LLM_MODEL` if set, else the show's
own model, else `DEFAULT_LLM_PROVIDER` + `DEFAULT_LLM_MODEL`. If none is set the job fails with
a message saying so. The call is logged and attributed to the show with `stage=discovery`
(usage capture records it with the others).

### Can the model search?

Before a job is queued BYOP checks that the model can search the web (`byop/services/web_search.py`)
and answers `yes`, `no` or `unknown`:

| Provider | Answer |
| --- | --- |
| OpenRouter | `yes` for `perplexity/…` and ids ending in `:online`; for any other model that is listed and produces text (the `:online` plugin then searches for it); `no` if the model produces no text or OpenRouter does not offer it; `unknown` if the model list cannot be read |
| OpenAI | `yes` only for the search models (ids containing `search`, e.g. `gpt-4o-search-preview`), otherwise `no` |
| A connection (`conn:<id>`) | the connection's **Web search** switch (Settings › Integrations): on is `yes`, off is `no` |
| anything else | `unknown` |

`no` refuses the request with `422` and a message that names the model and provider and says how
to fix it (nothing is queued); `unknown` is allowed, with the reason in the response's and the job's
`warnings`. The Discover dialog and the wizard's Sources step show the model that will be used, where
it comes from and this answer before you run anything. The worker applies the same check as a
safety net.

If the provider rejects the request anyway, the job's `error` explains it from what the provider
said (status, code and message, stripped of anything that looks like a key): a rejected key, no
credit, an unknown model, rate limiting, or a model that refuses the web-search request. It always
includes the provider's own words, and an unexpected failure names its kind instead of a bare
"failed".

| Method | Path | |
| --- | --- | --- |
| `POST` | `/api/shows/{id}/sources/discover` | Start for a show's topic; `202 {job_id, warnings}`, or `422` if the model cannot search |
| `POST` | `/api/sources/discover` | Start for a draft `{topic, language?, llm_provider?, llm_model?}` (before the show exists); same answers |
| `GET` | `/api/sources/discover/model` | The model discovery would use: `?show_id=` for a show, or `?llm_provider=&llm_model=` for a draft. `{provider, provider_label, model, source: discovery_setting\|show\|default, web_search: yes\|no\|unknown, message}`; `404` if no model is set up |
| `GET` | `/api/sources/discover/{job_id}` | `{status: queued\|running\|done\|failed, candidates, error, warnings}`; kept for an hour |

A candidate is `{kind, name, value, reason, recent_titles}`. Accepting one means creating the
source with `origin: "discovered"` through the normal sources API. Discovery is run on demand;
re-discovering on a schedule is not part of it.
