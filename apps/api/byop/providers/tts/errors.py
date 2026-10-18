class TTSError(Exception):
    """Speech synthesis failed (after retries)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TTSParamError(TTSError, ValueError):
    """The request cannot be sent: bad text, unsupported parameter or missing required one."""


class AudioConversionError(TTSError):
    """The provider's audio could not be converted to the canonical WAV."""
