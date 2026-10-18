# Episode audio

The `mix` stage of a [run](runs.md) turns the voiced chunks (see [voicing](tts.md)) into the finished
MP3 (`byop/services/audio_mix.py`, `byop/pipeline/stages/mix.py`). Everything goes through
`ffmpeg` subprocesses that read and write files, so memory use does not grow with the length of
the episode.

## What the mix does

1. **Speech track.** The chunk files are joined, in script order, with pauses between them (short
   silences generated on the fly; the files are joined by copying, not re-encoding):
   - 100 ms between the chunks of one line;
   - `AUDIO_SEGMENT_GAP_MS` (400 ms) between lines of the same story;
   - `AUDIO_TRANSITION_GAP_MS` (900 ms) at a **story change**: when a new story starts (a `story`
     line whose `item_ids` differ from the previous line's, or that follows the intro or a transition),
     around a `transition`, and before the `outro`.
   Chunks are checked first: each must be a 24 kHz mono 16-bit WAV, otherwise the run fails naming
   the file instead of producing garbage.
2. **Music bed (optional).** The show's music clip is looped under the whole speech track at
   `AUDIO_MUSIC_VOLUME_DB` (−22 dB), faded in and out over 2 seconds, and pushed further down by a
   sidechain compressor whenever someone is speaking (so it is audible in the pauses and quiet under
   the voices). It never lengthens the episode.
3. **Intro and outro (optional).** The show's clips are placed before and after the speech track
   (any sample rate or format ffmpeg reads).
4. **Loudness and encoding.** Everything is joined and normalised to `AUDIO_TARGET_LUFS` (−16 LUFS,
   the common podcast level; true peak −1.5 dB) with a two-pass `loudnorm` (measure, then a linear
   correction), then encoded as MP3 at `AUDIO_BITRATE_KBPS` (128 kbit/s), 44.1 kHz, mono or stereo
   (`AUDIO_CHANNELS`). Speech that is completely silent is encoded without normalisation.
5. **Result.** The file is streamed to storage as `shows/<show id>/episodes/<episode id>/audio.mp3`
   (local volume or S3, see [storage](storage.md)) and the draft episode gets `audio_key`,
   `duration_s` and `size_bytes`. Scratch files are removed when the run ends.

Without intro, outro or music the episode is just the speech with pauses, normalised and encoded.

## The show's intro, outro and music bed

In the show's **Settings › Audio**, or through the API (the show's owner only):

| Method | Path | |
| --- | --- | --- |
| `POST` | `/api/shows/{id}/audio/{kind}` | Upload (multipart `file`); `kind` is `intro`, `outro` or `music`; returns the show |
| `DELETE` | `/api/shows/{id}/audio/{kind}` | Remove |
| `GET` | `/api/shows/{id}/audio/{kind}` | The clip, for previewing |

Files must be audio (`mp3`, `wav`, `m4a`, `aac`, `ogg`, `oga`, `opus`, `flac`), at most 25 MB; an
intro or outro at most 2 minutes, a music bed at most 30 minutes. The file is checked with ffprobe,
streamed to disk (never held in memory) and stored under `shows/<show id>/audio/`. The show's
response has `intro_url`, `outro_url` and `music_url` (versioned, `null` when not set).

| Variable | Default | |
| --- | --- | --- |
| `AUDIO_TARGET_LUFS` | `-16` | Integrated loudness of the episode |
| `AUDIO_BITRATE_KBPS` | `128` | MP3 bitrate |
| `AUDIO_CHANNELS` | `1` | `1` mono (plenty for speech) or `2` stereo |
| `AUDIO_SEGMENT_GAP_MS` | `400` | Pause between lines |
| `AUDIO_TRANSITION_GAP_MS` | `900` | Pause between stories |
| `AUDIO_MUSIC_VOLUME_DB` | `-22` | Level of the music bed before ducking |

Tests generate sine-wave clips and measure the real output with ffmpeg (duration, loudness within
±0.7 LU of the target, silence in the pauses, the bed ducked under speech and looped), so they need
`ffmpeg` and `ffprobe` installed.
