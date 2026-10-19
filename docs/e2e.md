# End-to-end test

`make e2e` proves the whole product works from a clean clone, with no paid keys and no GPU. It
starts a throwaway copy of the stack and drives it in a real browser (Playwright):

1. sign in and see the getting-started checklist of a fresh install;
2. connect a language model (Settings › Integrations);
3. create a show with the Kokoro voices, then add a news feed as its source;
4. **Generate now** and watch the run to its end;
5. open the episode, check its audio loads and plays, approve it;
6. fetch the public feed and check it lists the episode, and that its audio answers a `Range`
   request with `206`;
7. check the dashboard and the history show it.

## Documentation pictures

`make screenshots` reuses this stack to regenerate the pictures of the README (`docs/images/`). It
needs no keys either: `tests/e2e/screenshots.spec.ts` seeds a demo show, "Open Source AI Weekly",
with two connections ("Local Ollama" for the model and "Studio voices" behind a gateway), the
mock servers' fuller news feed and three runs (two episodes published, one left as a draft), then
takes every picture at 1440×900 in the light theme and one in the dark theme. The PNGs are shrunk
with `tests/e2e/optimize-images.mjs` (palette quantisation, usually under 60 kB each). Look at each
picture before committing: nothing real may appear in them. `E2E_SCREENSHOTS=<dir>` is what makes
the spec run, so a plain `make e2e` skips it.

## The stack

`docker-compose.e2e.yml` adds one service to the normal stack, `mock-services`
(`tests/e2e/mock_llm/app.py`, run with the API image):

- an OpenAI-compatible chat API that answers the ranking and script prompts with canned but valid
  JSON built from what the prompt asks for (the speaker names, the story numbers, the length);
- a Kokoro-style speech API that returns a tone as long as the text;
- a small news feed with a few articles.

It also points `KOKORO_BASE_URL` at the mock, allows fetching sources from the compose network
(`SOURCES_ALLOW_PRIVATE_NETWORKS`), sets test-only credentials (`e2e@example.com`) and blanks any
provider keys from your `.env`, so a developer's real keys never reach the test.

`make e2e` runs it as its own compose project (`byop-e2e`) on port 18080 (`E2E_PORT`), so it does
not touch your running stack or data, and removes it, with its volumes, afterwards. `make e2e-down`
cleans up after an interrupted run. The first run installs the Playwright browser.

To iterate on the test itself, keep the stack up and run Playwright by hand:

```sh
COMPOSE_PROJECT_NAME=byop-e2e BYOP_WEB_PORT=18080 \
  docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --wait
cd tests/e2e && npm ci && npx playwright install chromium
E2E_BASE_URL=http://localhost:18080 npx playwright test    # --headed to watch
```

The test creates data, so reset the stack (`make e2e-down`, then up again) before each run.

## In CI

The `e2e` job of `.github/workflows/ci.yml` runs on every push to `main` (not on pull requests: it
builds the images and takes a few minutes). When it fails the run uploads an `e2e-failure`
artifact with the Playwright report, screenshots, video and trace, and the logs of every container.
Open a trace with `npx playwright show-trace <trace.zip>`.

The real model and voice servers are not part of it: they are covered by the unit tests with mocked
HTTP, and checked by hand against real providers.
