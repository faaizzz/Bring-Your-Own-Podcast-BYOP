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
