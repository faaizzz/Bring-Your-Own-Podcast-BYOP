# Voicing the script

The `tts` stage of a [run](runs.md) turns the draft episode's [script](scripts.md) into audio
chunks (`byop/services/synthesis.py`, `byop/pipeline/stages/tts.py`).

## What it does

1. **Chunking.** Each script segment is cut at sentence boundaries into chunks of at most the
   `max_chars_per_request` of its speaker's provider (4,096 for OpenAI, 5,000 for ElevenLabs, 800
   for Kokoro). Sentences are packed into chunks as full as the limit allows; only a sentence that is
   longer than the limit is cut (at a comma, then a space, then anywhere). A chunk belongs to one
   segment, so **a chunk never mixes speakers**.
2. **Synthesis.** Chunks are voiced concurrently, at most `TTS_CONCURRENCY` (4) at a time, each with
   its speaker's provider, voice and voice settings. Results come back in script order however
   the chunks finish. A provider can also limit how many requests it takes at once
   (`ProviderQuirks.max_concurrency`): a local Kokoro server on a CPU works through requests one at a
   time, so it is sent one, while chunks for other providers carry on in parallel. (On a CPU Kokoro takes
   roughly 0.15 s per character, so expect a long episode to take a while; a GPU is much faster.)
3. **Retry, then fallback, per chunk.** A failing chunk is retried `TTS_CHUNK_RETRIES` (2) more times
   with a delay that doubles from `TTS_RETRY_BACKOFF_S` (1 s); the providers also retry rate limits
   and server errors themselves. A request the provider rejects outright (an unsupported setting)
   is not retried. If the chunk still fails it is voiced with the speaker's **fallback provider and
   voice** (no voice settings), for that chunk only; the next chunk tries the main voice again. If the
   speaker has no fallback, or the fallback fails too, the run fails with the chunk number, the
   speaker, the provider and the reason. A fallback with a smaller request limit voices the chunk in
   several pieces.
4. **Progress.** After every chunk the run's progress moves along the stage's range (55-85 %) and the
   run is checked for cancellation. A chunk that used its fallback adds a warning to the run log.

## Output

Audio is canonical WAV (24 kHz, mono, 16-bit) streamed to disk by the providers; the stage only
keeps file paths in memory, so memory use does not grow with the length of the episode. Files go to
`MEDIA_ROOT/work/<run id>/tts/<chunk>-<piece>.wav` together with `MEDIA_ROOT/work/<run id>/manifest.json`:

```json
{
  "version": 1,
  "format": {"codec": "pcm_s16le", "sample_rate": 24000, "channels": 1},
  "characters": 1234,
  "cost_usd": null,
  "chunks": [
    {"index": 0, "segment": 0, "kind": "intro", "speaker": "Alex", "files": ["tts/00000-0.wav"],
     "provider": "openai", "voice_id": "alloy", "characters": 52, "cost_usd": null,
     "latency_ms": 840, "fallback": false}
  ]
}
```

The manifest is what the mixing step reads. It also carries the characters, cost (when a provider
reports one; `null` otherwise) and latency of **each chunk**, which is what usage capture needs. The
scratch directory belongs to the run: it is cleared at the start of the stage (a retried stage never
mixes in files from an earlier attempt) and deleted when the run ends, whether it succeeds, fails,
is cancelled or is reaped. All workers of a deployment need the same `MEDIA_ROOT` (a shared volume),
since the stages of one run may run on different workers.

| Variable | Default | |
| --- | --- | --- |
| `TTS_CONCURRENCY` | `4` | Chunks voiced at once (1-16) |
| `TTS_CHUNK_RETRIES` | `2` | Extra attempts per chunk before its fallback is used |
| `TTS_RETRY_BACKOFF_S` | `1` | First delay between attempts; doubles each time |
