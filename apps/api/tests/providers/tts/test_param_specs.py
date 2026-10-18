import pytest

from byop.models.enums import CredentialProvider as P
from byop.providers.tts import (
    ElevenLabsTTS,
    OpenAITTS,
    TTSParamError,
    UnsupportedTTSProvider,
    quirks_for,
    voice_param_problems,
)
from byop.providers.tts.base import ParamSpec
from tests.providers.tts.helpers import FAST_RETRY


@pytest.mark.parametrize(
    ("spec", "value", "expected"),
    [
        (ParamSpec("number", 0, 1), 0.5, None),
        (ParamSpec("number", 0, 1), 1, None),
        (ParamSpec("number", 0, 1), 1.01, "must be at most 1"),
        (ParamSpec("number", 0.25, 4), 0.1, "must be at least 0.25"),
        (ParamSpec("number"), "1", "must be a number"),
        (ParamSpec("number"), True, "must be a number"),
        (ParamSpec("integer", 0), 3, None),
        (ParamSpec("integer", 0), 3.5, "must be a whole number"),
        (ParamSpec("integer", 0), False, "must be a whole number"),
        (ParamSpec("boolean"), True, None),
        (ParamSpec("boolean"), 1, "must be true or false"),
        (ParamSpec("string", max_length=3), "abc", None),
        (ParamSpec("string", max_length=3), "abcd", "must be at most 3 characters"),
        (ParamSpec("string"), "  ", "must be a non-empty string"),
        (ParamSpec("string"), 5, "must be a non-empty string"),
    ],
)
def test_param_spec(spec: ParamSpec, value: object, expected: str | None) -> None:
    assert spec.problem(value) == expected


def test_every_provider_declares_a_spec_for_each_supported_param() -> None:
    for provider in (P.OPENAI, P.ELEVENLABS, P.OPENROUTER, P.KOKORO):
        quirks = quirks_for(provider)
        assert set(quirks.param_specs) == set(quirks.supported_params), provider


def test_voice_param_problems_covers_names_requirements_and_values() -> None:
    assert voice_param_problems(P.OPENAI, {"speed": 1.2, "instructions": "Calm"}) == {}
    assert voice_param_problems(P.OPENAI, {"stability": 0.5}) == {
        "stability": "is not supported by this provider"
    }
    assert voice_param_problems(P.OPENROUTER, {}) == {"model": "is required for this provider"}
    assert voice_param_problems(P.ELEVENLABS, {"speed": 2}) == {"speed": "must be at most 1.2"}
    assert voice_param_problems(P.KOKORO, {"format": "mp3"}) == {
        "format": "is not supported by this provider"
    }


def test_langfuse_is_not_a_tts_provider() -> None:
    with pytest.raises(UnsupportedTTSProvider):
        voice_param_problems(P.LANGFUSE, {})


async def test_synthesize_rejects_out_of_range_values_before_any_request(tmp_path: object) -> None:
    tts = OpenAITTS(api_key="sk-x", retry=FAST_RETRY)
    eleven = ElevenLabsTTS(api_key="xi-x", retry=FAST_RETRY)

    with pytest.raises(TTSParamError, match="speed.*at most 4"):
        await tts.synthesize("Hi", voice_id="alloy", output_dir=tmp_path, params={"speed": 9})  # type: ignore[arg-type]
    with pytest.raises(TTSParamError, match="stability.*at most 1"):
        await eleven.synthesize("Hi", voice_id="v", output_dir=tmp_path, params={"stability": 3})  # type: ignore[arg-type]
    await tts.aclose()
    await eleven.aclose()
