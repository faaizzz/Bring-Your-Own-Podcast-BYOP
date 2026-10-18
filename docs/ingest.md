# Ingest

Before each episode BYOP collects fresh, unique items for the show from its enabled
[sources](sources.md). It is the Celery task `byop.ingest_show(show_id, run_id=None)`
(`byop/tasks/ingest.py`), which calls `byop.services.ingest.pipeline.ingest_show`.

To try it by hand, run it inline and read the summary:

```sh
docker compose exec api python -m byop.cli ingest <show id or slug>
# Daily AI: 14 new, 0 updated, 40 fetched, 21 duplicates, 4 stale, 1 in another language, 0 invalid.
#   - BBC News: 21 items
#   - Hacker feed: error: The server answered HTTP 503
```

## What happens

1. **Fetch** every enabled source concurrently (6 at a time, each with a timeout of
   `INGEST_SOURCE_TIMEOUT_S`, 30 s by default). A source that fails records its reason in
   `last_error` and the others carry on; a source that works clears `last_error` and sets
   `last_fetched_at`.
   - `rss`: the feed's entries (at most 60 per fetch), with titles, links, plain-text summaries and
     dates. A URL that no longer serves a feed is an error.
   - `url`: the page's main text is extracted (readability-style: navigation and boilerplate
     removed) and becomes **one item** whose identity is the page URL. If the text changes, that
     item is updated and marked unused again, so a watched page can feed more than one episode.
   - `web_search`: a web-searching model is asked for recent items on the query (same model choice
     as [discovery](sources.md#discovering-sources), logged with `stage=ingest`). Without a model
     the source reports "No language model is set up for web search sources".
2. **Canonicalise** each URL: host lower-cased and without `www.`, `http` treated as `https`,
   default ports, fragments, trailing slashes and tracking parameters (`utm_*`, `fbclid`, `gclid`,
   ...) removed, remaining parameters sorted. Unusable URLs are counted as `invalid`.
3. **Filter**: items older than `INGEST_FRESHNESS_DAYS` (3) are `stale` (items without a date are
   kept); items confidently detected in another language than the show's are dropped (text that is
   too short to judge is kept). Dates are parsed from RFC 822 (RSS) and ISO 8601 (Atom) forms,
   and normalised to UTC; a time without a zone is taken as UTC.
4. **Deduplicate** against the show's stored items, each with a single SQL statement for the whole
   batch:
   - same canonical URL, or the same text (a hash of the title and the start of the summary);
   - near-identical headlines: `pg_trgm` `similarity(title) >=` `INGEST_TITLE_SIMILARITY`
     (0.55) against items collected within the last `INGEST_DEDUP_DAYS` (14), using the trigram
     index, and within the batch itself (the first one wins).
5. **Save** the rest as items (`ON CONFLICT DO NOTHING`).

Running it again is idempotent: everything already collected is recognised and skipped.
A benchmark test checks that 200 new items among 5,000 stored ones take well under 5 seconds
(that relies on Postgres having statistics for the table, which autovacuum provides).

Inside a run the task sets the run's `stage` to `ingest` and its progress to 5 and then 20.
Ranking and choosing which items go into the episode is a later step.

| Variable | Default | |
| --- | --- | --- |
| `INGEST_FRESHNESS_DAYS` | `3` | Items older than this are not collected |
| `INGEST_DEDUP_DAYS` | `14` | How far back titles are compared |
| `INGEST_TITLE_SIMILARITY` | `0.55` | Trigram similarity at which two headlines count as the same story |
| `INGEST_SOURCE_TIMEOUT_S` | `30` | Per-source time limit |
