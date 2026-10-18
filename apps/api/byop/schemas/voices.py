from pydantic import BaseModel


class VoiceResponse(BaseModel):
    id: str
    name: str
    language: str | None = None
    gender: str | None = None
    preview_url: str | None = None
