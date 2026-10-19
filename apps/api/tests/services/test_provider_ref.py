import uuid

import pytest
from pydantic import ValidationError

from byop.models.enums import CredentialProvider
from byop.schemas.speaker import SpeakerIn
from byop.services.provider_ref import InvalidProviderRef, ProviderRef
from tests.helpers import make_settings


def test_built_in_and_connection_references_round_trip() -> None:
    connection = uuid.uuid4()

    builtin = ProviderRef.parse("kokoro")
    conn = ProviderRef.parse(f"conn:{connection}")

    assert builtin.builtin is CredentialProvider.KOKORO and not builtin.is_connection
    assert conn.connection_id == connection and conn.is_connection
    assert conn.kind is CredentialProvider.OPENAI_COMPATIBLE
    assert (str(builtin), str(conn)) == ("kokoro", f"conn:{connection}")
    assert builtin == ProviderRef.of(CredentialProvider.KOKORO)


@pytest.mark.parametrize("raw", ["", "nope", "openai_compatible", "conn:", "conn:123", "CONN:x"])
def test_anything_else_is_invalid(raw: str) -> None:
    with pytest.raises(InvalidProviderRef):
        ProviderRef.parse(raw)


def test_schemas_and_settings_check_the_capability_of_a_built_in_provider() -> None:
    ref = f"conn:{uuid.uuid4()}"
    assert SpeakerIn(name="A", tts_provider=ref, voice_id="v").tts_provider == ref
    with pytest.raises(ValidationError):
        SpeakerIn(name="A", tts_provider="langfuse", voice_id="v")
    assert make_settings(default_llm_provider=ref).default_llm_provider == ref
    with pytest.raises(ValidationError):
        make_settings(default_llm_provider="elevenlabs")
    with pytest.raises(ValidationError):
        make_settings(default_llm_provider="openai_compatible")
