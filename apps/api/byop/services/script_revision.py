"""Which version of an episode's script exists, and which one its audio was voiced from.

Kept free of other imports so pipeline stages and the episode service can both use it.
"""

from collections.abc import Mapping


def revision_of(script: Mapping[str, object] | None) -> int:
    """The script's current revision; scripts written before revisions existed count as 1."""
    value = (script or {}).get("revision")
    return value if isinstance(value, int) and value >= 1 else 1


def audio_revision_of(script: Mapping[str, object] | None) -> int | None:
    """The revision the audio was voiced from, or None while there is no audio."""
    value = (script or {}).get("audio_revision")
    return value if isinstance(value, int) else None


def audio_is_current(script: Mapping[str, object] | None, has_audio: bool) -> bool:
    return has_audio and audio_revision_of(script) == revision_of(script)
