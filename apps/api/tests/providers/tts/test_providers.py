from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import respx

from byop.providers.common import CallMetadata
from byop.providers.tts import (
    CANONICAL_SAMPLE_RATE,
    ElevenLabsTTS,
    KokoroTTS,
    OpenAITTS,
    OpenRouterTTS,
    TTSError,
    TTSParamError,
    TTSProvider,
)
from tests.providers.tts.helpers import FAST_RETRY, json_body, mp3_bytes, pcm_bytes, read_wav


@dataclass(frozen=True)
class Case:
    name: str
    make: Callable[[], TTSProvider]
    url: str
    voice: str
    params: dict[str, object]


CASES = [
    Case(
        "openai",
        lambda: OpenAITTS(api_key="sk-test", retry=FAST_RETRY),
        "https://api.openai.com/v1/audio/speech",
        "alloy",
        {},
    ),
    Case(
        "elevenlabs",
        lambda: ElevenLabsTTS(api_key="xi-test", retry=FAST_RETRY),
        "https://api.elevenlabs.io/v1/text-to-speech/voice123",
        "voice123",
        {},
    ),
    Case(
        "openrouter",
        lambda: OpenRouterTTS(api_key="sk-or-test", retry=FAST_RETRY),
        "https://openrouter.ai/api/v1/audio/speech",
        "alloy",
        {"model": "openai/gpt-4o-mini-tts"},
    ),
    Case(
        "kokoro",
        lambda: KokoroTTS(base_url="http://kokoro:8880/v1", retry=FAST_RETRY),
        "http://kokoro:8880/v1/audio/speech",
        "af_bella",
        {},
    ),
]
every_provider = pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)

TEXT = "Welcome to the show."


async def synth(case: Case, out: Path, text: str = TEXT, **extra: object):  # type: ignore[no-untyped-def]
    provider = case.make()
    try:
        return await provider.synthesize(
            text,
            voice_id=case.voice,
            output_dir=out,
            params={**case.params, **extra},
            metadata=CallMetadata(stage="tts"),
        )
    finally:
        await provider.aclose()


def files(out: Path) -> list[str]:
    return sorted(p.name for p in out.iterdir()) if out.exists() else []


# --- audio normalisation ---------------------------------------------------------------------


@respx.mock
@every_provider
async def test_pcm_response_becomes_a_canonical_wav(case: Case, tmp_path: Path) -> None:
    pcm = pcm_bytes(2400)
    respx.post(case.url).respond(200, content=pcm)

    result = await synth(case, tmp_path)

    wav = read_wav(result.audio_path)
    assert (wav.channels, wav.sample_width, wav.rate) == (1, 2, CANONICAL_SAMPLE_RATE)
    assert wav.data == pcm  # untouched samples, just a header around them
    assert result.audio_path.parent == tmp_path and result.audio_path.suffix == ".wav"
    assert (result.format, result.sample_rate) == ("wav", 24000)
    assert result.cost_usd is None and result.latency_ms >= 0
    assert files(tmp_path) == [result.audio_path.name]  # no temporary files left behind


@respx.mock
@every_provider
async def test_mp3_response_is_converted_to_mono_24khz_wav(case: Case, tmp_path: Path) -> None:
    respx.post(case.url).respond(200, content=mp3_bytes(seconds=0.5, rate=44100, channels=2))

    result = await synth(case, tmp_path, format="mp3")

    wav = read_wav(result.audio_path)
    assert (wav.channels, wav.sample_width, wav.rate) == (1, 2, 24000)
    assert abs(wav.frames - 12000) < 2000  # ~0.5 s, allowing for MP3 encoder padding
    assert files(tmp_path) == [result.audio_path.name]


@respx.mock
@every_provider
async def test_large_responses_are_streamed_to_disk(case: Case, tmp_path: Path) -> None:
    pcm = pcm_bytes(1_500_000)  # 3 MB
    respx.post(case.url).respond(200, content=pcm)

    result = await synth(case, tmp_path)

    assert read_wav(result.audio_path).frames == 1_500_000


# --- characters, metadata ---------------------------------------------------------------------


@respx.mock
@every_provider
async def test_characters_are_counted_for_every_call(case: Case, tmp_path: Path) -> None:
    respx.post(case.url).respond(200, content=pcm_bytes())

    first = await synth(case, tmp_path, text="Hello there.")
    second = await synth(case, tmp_path, text="Ünïcode text — counts characters, not bytes.")

    assert first.characters == len("Hello there.")
    assert second.characters == len("Ünïcode text — counts characters, not bytes.")


@respx.mock
@every_provider
async def test_each_call_gets_its_own_file(case: Case, tmp_path: Path) -> None:
    respx.post(case.url).respond(200, content=pcm_bytes())

    a = await synth(case, tmp_path)
    b = await synth(case, tmp_path)

    assert a.audio_path != b.audio_path and len(files(tmp_path)) == 2


@respx.mock
@every_provider
async def test_the_output_directory_is_created_when_missing(case: Case, tmp_path: Path) -> None:
    respx.post(case.url).respond(200, content=pcm_bytes())

    result = await synth(case, tmp_path / "nested" / "dir")

    assert result.audio_path.exists()


# --- validation (before any HTTP) --------------------------------------------------------------


@respx.mock
@every_provider
async def test_invalid_requests_are_rejected_without_calling_the_provider(
    case: Case, tmp_path: Path
) -> None:
    route = respx.post(case.url).respond(200, content=pcm_bytes())
    limit = case.make().max_chars_per_request

    for bad in (
        {"text": "   "},
        {"text": "x" * (limit + 1)},
        {"extra": {"flavour": "spicy"}},
        {"extra": {"format": "flac"}},
    ):
        with pytest.raises(TTSParamError):
            await synth(case, tmp_path, bad.get("text", TEXT), **bad.get("extra", {}))  # type: ignore[arg-type]

    assert route.call_count == 0
    assert files(tmp_path) == []


@respx.mock
@every_provider
async def test_text_at_the_limit_is_accepted(case: Case, tmp_path: Path) -> None:
    respx.post(case.url).respond(200, content=pcm_bytes())
    limit = case.make().max_chars_per_request

    result = await synth(case, tmp_path, "x" * limit)

    assert result.characters == limit


# --- retries and errors ----------------------------------------------------------------------


@respx.mock
@every_provider
async def test_429_and_5xx_are_retried(case: Case, tmp_path: Path) -> None:
    route = respx.post(case.url).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(503),
            httpx.Response(200, content=pcm_bytes()),
        ]
    )

    result = await synth(case, tmp_path)

    assert route.call_count == 3
    assert result.audio_path.exists()


@respx.mock
@every_provider
async def test_retries_stop_at_the_limit(case: Case, tmp_path: Path) -> None:
    route = respx.post(case.url).respond(500, json={"error": "boom"})

    with pytest.raises(TTSError, match="HTTP 500") as excinfo:
        await synth(case, tmp_path)

    assert excinfo.value.status_code == 500
    assert route.call_count == FAST_RETRY.max_attempts
    assert files(tmp_path) == []


@respx.mock
@every_provider
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_client_errors_are_not_retried(case: Case, tmp_path: Path, status: int) -> None:
    route = respx.post(case.url).respond(status, json={"error": "nope sk-secret-value"})

    with pytest.raises(TTSError) as excinfo:
        await synth(case, tmp_path)

    assert excinfo.value.status_code == status
    assert route.call_count == 1
    assert "sk-secret-value" not in str(excinfo.value)  # provider bodies are not echoed
    assert files(tmp_path) == []


@respx.mock
@every_provider
async def test_network_errors_and_timeouts_are_retried_then_reported(
    case: Case, tmp_path: Path
) -> None:
    refused = respx.post(case.url).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(TTSError, match="Could not reach"):
        await synth(case, tmp_path)
    assert refused.call_count == FAST_RETRY.max_attempts

    refused.mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(TTSError, match="timed out"):
        await synth(case, tmp_path)
    assert files(tmp_path) == []


@respx.mock
@every_provider
async def test_an_empty_response_is_an_error(case: Case, tmp_path: Path) -> None:
    respx.post(case.url).respond(200, content=b"")

    with pytest.raises(TTSError, match="no audio"):
        await synth(case, tmp_path)

    assert files(tmp_path) == []


@respx.mock
@every_provider
async def test_audio_that_cannot_be_converted_is_an_error_and_leaves_nothing(
    case: Case, tmp_path: Path
) -> None:
    respx.post(case.url).respond(200, content=b"this is definitely not an mp3 file" * 50)

    with pytest.raises(TTSError, match="could not convert"):
        await synth(case, tmp_path, format="mp3")

    assert files(tmp_path) == []


@respx.mock
@every_provider
async def test_odd_length_pcm_is_rejected(case: Case, tmp_path: Path) -> None:
    respx.post(case.url).respond(200, content=pcm_bytes(100) + b"\x01")

    with pytest.raises(TTSError, match="odd number of bytes"):
        await synth(case, tmp_path)

    assert files(tmp_path) == []


# --- quirks live in one place ------------------------------------------------------------------


@every_provider
def test_every_provider_declares_complete_quirks(case: Case) -> None:
    quirks = case.make().quirks

    assert quirks.max_chars_per_request > 0
    assert quirks.default_format in quirks.formats
    assert quirks.timeout_s > 0
    assert quirks.required_params <= quirks.supported_params | {"format"}
    assert case.make().max_chars_per_request == quirks.max_chars_per_request


def test_declared_limits() -> None:
    assert OpenAITTS.quirks.max_chars_per_request == 4096
    assert ElevenLabsTTS.quirks.max_chars_per_request == 5000


# --- OpenAI ------------------------------------------------------------------------------------


@respx.mock
async def test_openai_request_shape(tmp_path: Path) -> None:
    route = respx.post("https://api.openai.com/v1/audio/speech").respond(200, content=pcm_bytes())
    provider = OpenAITTS(api_key="sk-test", retry=FAST_RETRY)

    await provider.synthesize(
        TEXT,
        voice_id="nova",
        output_dir=tmp_path,
        params={"model": "tts-1-hd", "speed": 1.25, "instructions": "Warm and calm."},
    )
    await provider.aclose()

    assert json_body(route) == {
        "model": "tts-1-hd",
        "input": TEXT,
        "voice": "nova",
        "response_format": "pcm",
        "speed": 1.25,
        "instructions": "Warm and calm.",
    }
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-test"


@respx.mock
async def test_openai_defaults_and_mp3_request(tmp_path: Path) -> None:
    route = respx.post("https://api.openai.com/v1/audio/speech").respond(200, content=mp3_bytes())
    provider = OpenAITTS(api_key="sk-test", retry=FAST_RETRY)

    await provider.synthesize(TEXT, voice_id="alloy", output_dir=tmp_path, params={"format": "mp3"})
    await provider.aclose()

    body = json_body(route)
    assert body["model"] == "gpt-4o-mini-tts" and body["response_format"] == "mp3"
    assert "speed" not in body and "instructions" not in body


@respx.mock
async def test_openai_compatible_base_url(tmp_path: Path) -> None:
    route = respx.post("https://tts.example/v1/audio/speech").respond(200, content=pcm_bytes())
    provider = OpenAITTS(api_key="k", base_url="https://tts.example/v1/", retry=FAST_RETRY)

    await provider.synthesize(TEXT, voice_id="v", output_dir=tmp_path)
    await provider.aclose()

    assert route.called


async def test_openai_lists_its_builtin_voices() -> None:
    provider = OpenAITTS(api_key="k")
    voices = await provider.list_voices()
    await provider.aclose()

    assert {"alloy", "nova", "onyx"} <= {v.id for v in voices}
    assert next(v for v in voices if v.id == "alloy").name == "Alloy"


# --- ElevenLabs --------------------------------------------------------------------------------


@respx.mock
async def test_elevenlabs_request_shape(tmp_path: Path) -> None:
    route = respx.post("https://api.elevenlabs.io/v1/text-to-speech/voice%2F123").respond(
        200, content=pcm_bytes()
    )
    provider = ElevenLabsTTS(api_key="xi-test", retry=FAST_RETRY)

    await provider.synthesize(
        TEXT,
        voice_id="voice/123",
        output_dir=tmp_path,
        params={
            "model_id": "eleven_flash_v2_5",
            "stability": 0.4,
            "similarity_boost": 0.8,
            "speed": 1.1,
            "language_code": "en",
            "seed": 7,
        },
    )
    await provider.aclose()

    request = route.calls.last.request
    assert request.headers["xi-api-key"] == "xi-test"
    assert request.url.params["output_format"] == "pcm_24000"
    assert json_body(route) == {
        "text": TEXT,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "speed": 1.1},
        "language_code": "en",
        "seed": 7,
    }


@respx.mock
async def test_elevenlabs_default_model_and_mp3_output(tmp_path: Path) -> None:
    route = respx.post("https://api.elevenlabs.io/v1/text-to-speech/v1").respond(
        200, content=mp3_bytes()
    )
    provider = ElevenLabsTTS(api_key="xi-test", retry=FAST_RETRY)

    await provider.synthesize(TEXT, voice_id="v1", output_dir=tmp_path, params={"format": "mp3"})
    await provider.aclose()

    assert route.calls.last.request.url.params["output_format"] == "mp3_44100_128"
    assert json_body(route) == {"text": TEXT, "model_id": "eleven_multilingual_v2"}


@respx.mock
async def test_elevenlabs_voice_list_is_mapped() -> None:
    respx.get("https://api.elevenlabs.io/v1/voices").respond(
        200,
        json={
            "voices": [
                {
                    "voice_id": "abc",
                    "name": "Rachel",
                    "labels": {"gender": "female", "language": "en"},
                    "preview_url": "https://cdn.example/rachel.mp3",
                },
                {
                    "voice_id": "def",
                    "name": "Hans",
                    "labels": {},
                    "verified_languages": [{"language": "de"}],
                },
                {"voice_id": "ghi"},
                {"name": "no id"},
            ]
        },
    )
    provider = ElevenLabsTTS(api_key="xi-test", retry=FAST_RETRY)

    voices = await provider.list_voices()
    await provider.aclose()

    rachel, hans, bare = voices
    assert (rachel.id, rachel.name, rachel.language, rachel.gender) == (
        "abc",
        "Rachel",
        "en",
        "female",
    )
    assert rachel.preview_url == "https://cdn.example/rachel.mp3"
    assert (hans.language, hans.gender, hans.preview_url) == ("de", None, None)
    assert (bare.id, bare.name) == ("ghi", "ghi")


@respx.mock
async def test_elevenlabs_voice_list_errors_are_reported() -> None:
    respx.get("https://api.elevenlabs.io/v1/voices").respond(401, json={"detail": "bad key"})
    provider = ElevenLabsTTS(api_key="xi-test", retry=FAST_RETRY)

    with pytest.raises(TTSError, match="HTTP 401"):
        await provider.list_voices()
    await provider.aclose()


# --- OpenRouter --------------------------------------------------------------------------------


@respx.mock
async def test_openrouter_needs_a_model_and_sends_attribution(tmp_path: Path) -> None:
    route = respx.post("https://openrouter.ai/api/v1/audio/speech").respond(
        200, content=pcm_bytes()
    )
    provider = OpenRouterTTS(api_key="sk-or-test", retry=FAST_RETRY)

    with pytest.raises(TTSParamError, match="requires parameter.*model"):
        await provider.synthesize(TEXT, voice_id="alloy", output_dir=tmp_path)
    await provider.synthesize(
        TEXT, voice_id="alloy", output_dir=tmp_path, params={"model": "vendor/tts-1"}
    )
    await provider.aclose()

    assert json_body(route)["model"] == "vendor/tts-1"
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer sk-or-test"
    assert request.headers["x-title"] == "BYOP"
