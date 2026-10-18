import re
import subprocess
from pathlib import Path

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr

from byop.config import get_settings
from tests.helpers import make_settings
from tests.providers.tts.helpers import json_body, pcm_bytes

URL = "/api/voices/preview"
ONE_SECOND = pcm_bytes(24000)  # 24 kHz mono 16-bit

# provider -> (settings that configure it, upstream URL pattern, request params)
CASES: dict[str, tuple[dict[str, object], str | re.Pattern[str], dict[str, object]]] = {
    "openai": (
        {"openai_api_key": SecretStr("sk-env-key-0123456789")},
        "https://api.openai.com/v1/audio/speech",
        {"speed": 1.1},
    ),
    "elevenlabs": (
        {"elevenlabs_api_key": SecretStr("xi-env-key-0123456789")},
        re.compile(r"https://api\.elevenlabs\.io/v1/text-to-speech/voice-1.*"),
        {"stability": 0.5},
    ),
    "openrouter": (
        {"openrouter_api_key": SecretStr("sk-or-env-key-123456")},
        "https://openrouter.ai/api/v1/audio/speech",
        {"model": "openai/gpt-4o-mini-tts"},
    ),
    "kokoro": (
        {"kokoro_base_url": "http://kokoro:8880/v1"},
        "http://kokoro:8880/v1/audio/speech",
        {"speed": 0.9},
    ),
}


def configure(app: FastAPI, tmp_path: Path, **overrides: object) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        media_root=str(tmp_path), **overrides
    )


def probe(mp3: bytes, directory: Path) -> tuple[str, float]:
    """Codec name and duration of an audio file, as ffprobe sees it."""
    clip = directory / "clip.mp3"
    clip.write_bytes(mp3)
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name:format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(clip),
        ],  # fmt: skip
        capture_output=True,
        check=True,
    )
    codec, duration = result.stdout.decode().split()
    return codec, float(duration)


@pytest.mark.parametrize("provider", sorted(CASES))
@respx.mock
async def test_every_provider_returns_an_mp3_and_caches_it(
    provider: str, app: FastAPI, authed: AsyncClient, tmp_path: Path
) -> None:
    settings, upstream, params = CASES[provider]
    configure(app, tmp_path, **settings)
    route = respx.post(upstream).respond(200, content=ONE_SECOND)
    body = {"provider": provider, "voice_id": "voice-1", "params": params}

    first = await authed.post(URL, json=body)

    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "audio/mpeg"
    codec, duration = probe(first.content, tmp_path)
    assert codec == "mp3" and 0.9 < duration < 1.2
    assert route.call_count == 1
    assert len(list((tmp_path / "previews").glob("*.mp3"))) == 1

    second = await authed.post(URL, json=body)

    assert second.status_code == 200 and second.content == first.content
    assert route.call_count == 1  # served from storage


@respx.mock
async def test_the_request_reaches_the_provider_with_voice_text_and_params(
    app: FastAPI, authed: AsyncClient, tmp_path: Path
) -> None:
    configure(app, tmp_path, openai_api_key=SecretStr("sk-env-key-0123456789"))
    route = respx.post("https://api.openai.com/v1/audio/speech").respond(200, content=ONE_SECOND)

    await authed.post(
        URL,
        json={"provider": "openai", "voice_id": "nova", "params": {"speed": 1.5}, "text": "Hi!"},
    )

    sent = json_body(route)
    assert (sent["voice"], sent["input"], sent["speed"]) == ("nova", "Hi!", 1.5)


@respx.mock
async def test_different_voices_params_or_text_are_different_clips(
    app: FastAPI, authed: AsyncClient, tmp_path: Path
) -> None:
    configure(app, tmp_path, openai_api_key=SecretStr("sk-env-key-0123456789"))
    route = respx.post("https://api.openai.com/v1/audio/speech").respond(200, content=ONE_SECOND)
    base = {"provider": "openai", "voice_id": "alloy"}

    await authed.post(URL, json=base)
    await authed.post(URL, json={**base, "voice_id": "nova"})
    await authed.post(URL, json={**base, "params": {"speed": 2}})
    await authed.post(URL, json={**base, "text": "Something else"})
    await authed.post(URL, json={**base, "params": {}})  # same as the first

    assert route.call_count == 4
    assert len(list((tmp_path / "previews").glob("*.mp3"))) == 4


async def test_bad_params_are_reported_per_field(
    app: FastAPI, authed: AsyncClient, tmp_path: Path
) -> None:
    configure(app, tmp_path, openai_api_key=SecretStr("sk-env-key-0123456789"))

    response = await authed.post(
        URL,
        json={
            "provider": "openai",
            "voice_id": "alloy",
            "params": {"speed": 10, "stability": 1, "format": "mp3"},
        },
    )

    assert response.status_code == 422
    found = {tuple(d["loc"]): d["msg"] for d in response.json()["detail"]}
    assert found[("body", "params", "speed")] == "must be at most 4"
    assert ("body", "params", "stability") in found
    assert ("body", "params", "format") in found  # chosen by the pipeline, not the speaker


async def test_request_shape_is_validated(authed: AsyncClient) -> None:
    for bad in (
        {"provider": "nope", "voice_id": "x"},
        {"provider": "openai", "voice_id": ""},
        {"provider": "openai", "voice_id": "x", "text": "y" * 301},
        {"provider": "openai", "voice_id": "x", "text": "   "},
    ):
        assert (await authed.post(URL, json=bad)).status_code == 422, bad


async def test_unconfigured_provider_is_a_conflict(authed: AsyncClient) -> None:
    response = await authed.post(URL, json={"provider": "elevenlabs", "voice_id": "x"})

    assert response.status_code == 409


@respx.mock
async def test_upstream_failure_is_a_bad_gateway_and_nothing_is_cached(
    app: FastAPI, authed: AsyncClient, tmp_path: Path
) -> None:
    configure(app, tmp_path, openai_api_key=SecretStr("sk-env-key-0123456789"))
    respx.post("https://api.openai.com/v1/audio/speech").mock(
        return_value=httpx.Response(401, json={"error": "bad key"})
    )

    response = await authed.post(URL, json={"provider": "openai", "voice_id": "alloy"})

    assert response.status_code == 502
    assert "401" in response.json()["detail"]
    assert not (tmp_path / "previews").exists()


async def test_requires_a_session(client: AsyncClient) -> None:
    assert (await client.post(URL, json={"provider": "openai", "voice_id": "a"})).status_code == 401
