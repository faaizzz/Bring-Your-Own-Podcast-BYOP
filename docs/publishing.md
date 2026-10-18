# Publishing to podcast directories

Your show's feed is `<PUBLIC_BASE_URL>/feeds/<slug>.xml` ([feed](feed.md) explains its contents). Any
podcast app can subscribe to it; directories list it after you submit it once.

## Before you submit

1. **Make BYOP reachable on the internet over https.** Set `PUBLIC_BASE_URL` to its public address
   (for example `https://pods.example.com`) and restart. Directories fetch your feed and audio
   from that address; `http://localhost:8080` only works on your own machine. Put a reverse proxy
   with a certificate in front of the `web` service, for example with Caddy:

   ```
   pods.example.com {
       reverse_proxy localhost:8080
   }
   ```

   Keep `X-Forwarded-For` and `X-Forwarded-Proto` headers (proxies do by default). Everything except
   the feed, episode audio and covers needs a login, so exposing it does not publish your data; do
   change `BYOP_ADMIN_PASSWORD` first ([security](security.md)).
2. **Upload a cover** (Settings tab of the show): a square of 1400-3000 px; BYOP crops and scales
   what you give it. Apple Podcasts rejects feeds without one.
3. **Fill the feed settings:** author, contact email, category and the explicit flag.
4. **Publish at least one episode** (approve a draft, or use `auto_publish`). Directories refuse an
   empty feed.
5. Check the feed with a validator such as Cast Feed Validator or Podbase. The feed address is on the
   show's Overview tab, with a copy button.

## Apple Podcasts

In Apple Podcasts Connect choose *Add a show*, then *Add a show with an RSS feed*, and paste the feed
address. Apple verifies the owner by emailing the feed's owner address, so set a mailbox you read as
the feed email. Review usually takes a few days; later episodes appear by themselves.

## Spotify

In Spotify for Creators choose *Add your podcast* (you already have one) and paste the feed address;
confirm ownership through the code sent to the feed email. New episodes are picked up automatically.

## Other apps and directories

Pocket Casts, Overcast, Castro, AntennaPod and most others accept a feed address directly
(*Add by URL* / *Custom feed*). Directories such as Podcast Index, YouTube Music and Amazon Music
each have a submission form that asks for the same address.

## Keeping it healthy

- Keep the address stable: it is part of the feed and the show's slug cannot change once an episode
  is published. Moving to another domain only needs `PUBLIC_BASE_URL` changed; episode GUIDs stay the
  same so apps do not list episodes twice (tell the directories the new feed address).
- Turn the feed off with the switch on the show's Overview tab (the address then answers
  "not found"); published episodes' audio stays reachable by its address.
- Audio is served with `Range` support and cached; for a very popular show serve media from S3 or a
  CDN ([storage](storage.md)).
