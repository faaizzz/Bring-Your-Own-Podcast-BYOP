from pathlib import Path

import pytest
import respx

from byop.providers.tts import KokoroTTS, TTSError
from byop.providers.tts.kokoro_tts import describe_voice
from tests.providers.tts.helpers import FAST_RETRY, json_body, pcm_bytes, read_wav

BASE = "http://kokoro:8880/v1"


@respx.mock
async def test_request_shape_has_no_credentials(tmp_path: Path) -> None:
    route = respx.post(f"{BASE}/audio/speech").respond(200, content=pcm_bytes())
    tts = KokoroTTS(base_url=BASE + "/", retry=FAST_RETRY)

    result = await tts.synthesize(
        "Hello from Kokoro.",
        voice_id="af_bella+af_sky",
        output_dir=tmp_path,
        params={"speed": 1.1, "lang_code": "a"},
    )
    await tts.aclose()

    assert json_body(route) == {
        "model": "kokoro",
        "input": "Hello from Kokoro.",
        "voice": "af_bella+af_sky",
        "response_format": "pcm",
        "speed": 1.1,
        "lang_code": "a",
    }
    assert "authorization" not in route.calls.last.request.headers
    assert read_wav(result.audio_path).rate == 24000
    assert result.characters == len("Hello from Kokoro.")


@respx.mock
async def test_voice_objects_from_kokoro_fastapi_are_understood() -> None:
    respx.get(f"{BASE}/audio/voices").respond(
        200,
        json={
            "voices": [
                {"id": "af_alloy", "name": "af_alloy", "overall_grade": "C"},
                {"id": "bm_george"},
                {"name": "no id"},
            ]
        },
    )
    tts = KokoroTTS(base_url=BASE, retry=FAST_RETRY)

    voices = await tts.list_voices()
    await tts.aclose()

    assert [(v.id, v.gender, v.language) for v in voices] == [
        ("af_alloy", "female", "en-US"),
        ("bm_george", "male", "en-GB"),
    ]


@respx.mock
async def test_voice_list_is_decoded_into_names_languages_and_genders() -> None:
    respx.get(f"{BASE}/audio/voices").respond(
        200, json={"voices": ["af_bella", "bm_george", "jf_alpha", "pf_dora", "weird", 7]}
    )
    tts = KokoroTTS(base_url=BASE, retry=FAST_RETRY)

    voices = await tts.list_voices()
    await tts.aclose()

    by_id = {v.id: v for v in voices}
    assert list(by_id) == ["af_bella", "bm_george", "jf_alpha", "pf_dora", "weird"]
    assert (by_id["af_bella"].name, by_id["af_bella"].language, by_id["af_bella"].gender) == (
        "Bella",
        "en-US",
        "female",
    )
    assert (by_id["bm_george"].language, by_id["bm_george"].gender) == ("en-GB", "male")
    assert by_id["jf_alpha"].language == "ja" and by_id["pf_dora"].language == "pt-BR"
    assert (by_id["weird"].name, by_id["weird"].language, by_id["weird"].gender) == (
        "weird",
        None,
        None,
    )


@respx.mock
async def test_an_unreachable_server_is_a_tts_error() -> None:
    import httpx

    respx.get(f"{BASE}/audio/voices").mock(side_effect=httpx.ConnectError("down"))
    tts = KokoroTTS(base_url=BASE, retry=FAST_RETRY)

    with pytest.raises(TTSError, match="Could not reach kokoro"):
        await tts.list_voices()
    await tts.aclose()


@pytest.mark.parametrize(
    ("voice_id", "name"),
    [("af_heart", "Heart"), ("am_michael", "Michael"), ("bf_emma", "Emma"), ("ef_dora", "Dora")],
)
def test_describe_voice_names(voice_id: str, name: str) -> None:
    assert describe_voice(voice_id).name == name


def test_cpu_synthesis_gets_a_generous_timeout() -> None:
    assert KokoroTTS.quirks.timeout_s >= 300
