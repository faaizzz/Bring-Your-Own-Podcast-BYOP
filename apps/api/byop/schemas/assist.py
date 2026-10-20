from typing import Annotated

from pydantic import BaseModel, StringConstraints, model_validator

from byop.schemas.show import LLMProviderName

Brief = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Language = Annotated[str, StringConstraints(strip_whitespace=True, max_length=16)]


class AssistRequest(BaseModel):
    """What to design, and optionally which model designs it (else the instance default)."""

    brief: Brief
    # The language the show is in; the name and description are written in it.
    language: Language | None = None
    provider: LLMProviderName | None = None
    model: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None

    @model_validator(mode="after")
    def _model_comes_with_its_provider(self) -> "AssistRequest":
        if (self.provider is None) != (not self.model):
            raise ValueError("provider and model must be given together")
        return self


# The drafts are also what the model is asked to answer with, so their limits are the same as
# those of a saved style or persona: a draft that breaks them is repaired once, then refused.
class StyleDraft(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    instructions: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)
    ]


class PersonaDraft(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    persona: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
