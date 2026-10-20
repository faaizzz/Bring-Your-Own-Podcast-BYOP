import httpx
import pytest
import respx

from byop.models.enums import CredentialProvider
from byop.providers.tts import (
    ElevenLabsTTS,
    KokoroTTS,
    OpenAICompatibleTTS,
    OpenAITTS,
    OpenRouterTTS,
    TTSError,
    quirks_for,
)
from byop.providers.tts.openrouter_tts import FALLBACK_MODELS
from tests.providers.tts.helpers import FAST_RETRY

OPENROUTER_SPEECH = "https://openrouter.ai/api/v1/models?output_modalities=speech"
SPEECH_PAYLOAD = {
    "data": [
        {
            "id": "mistralai/voxtral-mini-tts-3-0",
            "name": "Mistral: Voxtral TTS 3",
            "description": "Preset voices and cloning.",
            "architecture": {"output_modalities": ["speech"]},
            "supported_voices": ["en_paul_neutral", "fr_marie_happy"],
        },
        {"id": "hexgrad/kokoro-82m", "name": "Kokoro", "supported_voices": ["af_bella", 7]},
        {"id": "no-voices/tts", "name": "No voices listed"},
        {"name": "no id"},
        "junk",
    ]
}


@respx.mock
async def test_openrouter_asks_for_speech_models_only_and_keeps_their_voices() -> None:
    route = respx.get(OPENROUTER_SPEECH).respond(200, json=SPEECH_PAYLOAD)
    tts = OpenRouterTTS(api_key="sk-or-test", retry=FAST_RETRY)

    models = await tts.list_models()

    assert [m.id for m in models] == [
        "mistralai/voxtral-mini-tts-3-0",
        "hexgrad/kokoro-82m",
        "no-voices/tts",
    ]
    assert models[0].name == "Mistral: Voxtral TTS 3"
    assert models[0].voices == ("en_paul_neutral", "fr_marie_happy")
    assert models[1].voices == ("af_bella",)  # anything that is not a string is dropped
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-or-test"
    await tts.aclose()


@respx.mock
async def test_openrouter_voices_follow_the_chosen_model() -> None:
    respx.get(OPENROUTER_SPEECH).respond(200, json=SPEECH_PAYLOAD)
    tts = OpenRouterTTS(api_key="sk-or-test", retry=FAST_RETRY)

    chosen = await tts.list_voices("mistralai/voxtral-mini-tts-3-0")
    no_list = await tts.list_voices("no-voices/tts")
    unknown = await tts.list_voices("nobody/knows")
    none_yet = await tts.list_voices()

    assert [v.id for v in chosen] == ["en_paul_neutral", "fr_marie_happy"]
    assert "alloy" in {v.id for v in no_list}  # OpenAI's names when the model lists none
    assert [v.id for v in unknown] == [v.id for v in none_yet] == [v.id for v in no_list]
    await tts.aclose()


@respx.mock
async def test_openrouter_offers_a_curated_list_when_it_lists_no_speech_model() -> None:
    respx.get(OPENROUTER_SPEECH).respond(200, json={"data": []})
    tts = OpenRouterTTS(api_key="sk-or-test", retry=FAST_RETRY)

    assert await tts.list_models() == list(FALLBACK_MODELS)
    await tts.aclose()


@respx.mock
async def test_openrouter_errors_are_not_hidden_behind_the_fallback() -> None:
    respx.get(OPENROUTER_SPEECH).respond(401)
    tts = OpenRouterTTS(api_key="sk-or-bad", retry=FAST_RETRY)

    with pytest.raises(TTSError):
        await tts.list_models()
    await tts.aclose()


async def test_openai_lists_its_known_speech_models() -> None:
    tts = OpenAITTS(api_key="sk-test", retry=FAST_RETRY)

    models = await tts.list_models()

    assert [m.id for m in models] == ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"]
    assert tts.default_model == "gpt-4o-mini-tts"
    await tts.aclose()


@respx.mock
async def test_elevenlabs_lists_the_models_that_can_speak() -> None:
    route = respx.get("https://api.elevenlabs.io/v1/models").respond(
        200,
        json=[
            {
                "model_id": "eleven_multilingual_v2",
                "name": "Eleven Multilingual v2",
                "description": "Lifelike.",
                "can_do_text_to_speech": True,
            },
            {"model_id": "scribe", "name": "Scribe", "can_do_text_to_speech": False},
            {"model_id": "eleven_flash_v2_5"},
        ],
    )
    tts = ElevenLabsTTS(api_key="xi-test", retry=FAST_RETRY)

    models = await tts.list_models()

    assert [(m.id, m.name) for m in models] == [
        ("eleven_multilingual_v2", "Eleven Multilingual v2"),
        ("eleven_flash_v2_5", "eleven_flash_v2_5"),
    ]
    assert route.calls.last.request.headers["xi-api-key"] == "xi-test"
    assert tts.default_model == "eleven_multilingual_v2"
    await tts.aclose()


@respx.mock
async def test_a_connection_lists_its_servers_models_or_none() -> None:
    respx.get("http://llm.local/v1/models").respond(
        200, json={"data": [{"id": "kokoro"}, {"id": "xtts"}, {"nope": 1}]}
    )
    respx.get("http://plain.local/v1/models").respond(404)
    respx.get("http://down.local/v1/models").mock(side_effect=httpx.ConnectError("down"))
    listing = OpenAICompatibleTTS(base_url="http://llm.local/v1", retry=FAST_RETRY)
    plain = OpenAICompatibleTTS(base_url="http://plain.local/v1", retry=FAST_RETRY)
    down = OpenAICompatibleTTS(base_url="http://down.local/v1", retry=FAST_RETRY)

    assert [m.id for m in await listing.list_models()] == ["kokoro", "xtts"]
    assert await plain.list_models() == []  # the user types the model
    assert await down.list_models() == []
    for tts in (listing, plain, down):
        await tts.aclose()


async def test_providers_without_a_choice_of_model_list_none() -> None:
    tts = KokoroTTS(base_url="http://kokoro:8880/v1", retry=FAST_RETRY)

    assert await tts.list_models() == []
    assert quirks_for(CredentialProvider.KOKORO).model_param is None
    await tts.aclose()


def test_each_provider_names_its_model_parameter() -> None:
    names = {p: quirks_for(p).model_param for p in CredentialProvider if p.value in _TTS}

    assert names == {
        CredentialProvider.OPENAI: "model",
        CredentialProvider.ELEVENLABS: "model_id",
        CredentialProvider.OPENROUTER: "model",
        CredentialProvider.KOKORO: None,
        CredentialProvider.OPENAI_COMPATIBLE: "model",
    }
    # A model name is only required where there is no sensible default.
    assert quirks_for(CredentialProvider.OPENROUTER).required_params == {"model"}
    assert quirks_for(CredentialProvider.OPENROUTER).voices_follow_model
    assert not quirks_for(CredentialProvider.OPENAI).voices_follow_model


_TTS = {"openai", "elevenlabs", "openrouter", "kokoro", "openai_compatible"}
