# Podcast feed and public audio

Every show has a public RSS feed that podcast apps and directories can subscribe to. No login is
needed to read it or the audio it points to.

| Address | |
| --- | --- |
| `/feeds/<slug>.xml` | The feed: RSS 2.0 with the iTunes and Podcasting 2.0 namespaces |
| `/media/episodes/<id>.mp3` | The audio of a **published** episode (`GET` and `HEAD`, `Range` supported) |

All addresses inside the feed are absolute and built from `PUBLIC_BASE_URL`, so set it to the
address your instance is reachable at, e.g. `https://pods.example.com`. Directories need a public
https address; `http://localhost:8080` only works on your own machine (the app warns about this
under the feed address). If the address changes later, episode GUIDs stay the same, so apps do not
list the episodes twice.

## What is in the feed

- **Channel:** `title`, `link`, `description` (the show's description, else its topic), `language`,
  `atom:link rel="self"`, `lastBuildDate`, `itunes:author` (the feed author, else the title),
  `itunes:type` (`episodic`), `itunes:explicit`, `itunes:category` (the show's feed category, else
  `News`), `itunes:owner` with the feed email when set, `itunes:image` and `image` (the cover, a
  1400-3000 px square, see [storage](storage.md)) once a cover is uploaded, and `podcast:guid`.
- **Items:** published episodes only, newest first. `title`, `description`, `guid` (the episode id,
  `isPermaLink="false"`), `pubDate`, an `enclosure` with `url`, `length` (bytes) and
  `type="audio/mpeg"`, `itunes:duration`, `itunes:explicit`, `itunes:episode` (publication order, so
  a number never changes) and `itunes:episodeType`.
- Drafts and rejected episodes never appear, and neither does an episode without audio.

The author, email, category and explicit flag are the show's *feed* settings (Settings tab). A cover
is required by Apple Podcasts. The feed answers with an `ETag` and `Cache-Control: public,
max-age=300`; a request with a matching `If-None-Match` gets `304`.

## Turning the feed off

Each show has `feed_enabled` (default on; the switch is on the show's Overview tab, or
`PATCH /api/shows/{id}` with `{"feed_enabled": false}`). A disabled or unknown feed answers `404`.
Audio of already published episodes stays reachable by its address. `GET /api/shows/{id}` returns
the feed address as `feed_url`.

## Audio and `Range`

`/media/episodes/<id>.mp3` is served with `Accept-Ranges: bytes`: a `Range` request answers `206` with
a `Content-Range` (a range past the end is `416`), so apps can seek and resume downloads. It is
streamed from the configured [storage](storage.md) and cached for a day (a published episode never
changes). A draft or unknown id is `404`.

`docker/nginx.conf` forwards `/feeds/` and `/media/` to the API without buffering.

## Submitting the feed

- **Apple Podcasts:** in Apple Podcasts Connect choose *Add a show*, then *Add a show with an RSS
  feed*, and paste the feed address.
- **Spotify:** in Spotify for Creators choose *Add your podcast* (you already have one) and paste
  the feed address.
- **Other apps** (Pocket Casts, Overcast, ...): add the address as a custom feed.

Publish at least one episode first; directories reject an empty feed. Check it with a validator
such as Cast Feed Validator or Podbase before submitting.
