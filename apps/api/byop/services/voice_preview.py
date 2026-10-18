import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import anyio

from byop.providers.tts import TTSProvider, wav_to_mp3
from byop.services.storage import Storage

DEFAULT_TEXT = "Hello, and welcome to the show. This is how I sound."
PREVIEW_PREFIX = "previews"


def preview_key(provider: str, voice_id: str, params: Mapping[str, object], text: str) -> str:
    """Storage key of a clip: identical requests share one file."""
    canonical = json.dumps(
        {"provider": provider, "voice": voice_id, "params": params, "text": text},
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{PREVIEW_PREFIX}/{hashlib.sha256(canonical.encode()).hexdigest()}.mp3"


async def render_preview(
    storage: Storage,
    tts: TTSProvider,
    *,
    voice_id: str,
    params: Mapping[str, object],
    text: str | None,
) -> bytes:
    """A short MP3 of `voice_id` speaking `text`, synthesized once and then served from storage."""
    sample = text or DEFAULT_TEXT
    key = preview_key(tts.name, voice_id, params, sample)
    if (cached := await storage.read(key)) is not None:
        return cached

    async with anyio.TemporaryDirectory() as tmp:
        work = Path(tmp)
        result = await tts.synthesize(sample, voice_id=voice_id, output_dir=work, params=params)
        mp3 = work / "preview.mp3"
        await wav_to_mp3(result.audio_path, mp3)
        data = await anyio.Path(mp3).read_bytes()
    await storage.write(key, data)
    return data
