from byop.config import Settings
from byop.models import Show
from byop.services.provider_ref import ProviderRef


def instance_model(settings: Settings) -> tuple[ProviderRef, str] | None:
    """The instance's default language model, for work that belongs to no show."""
    if settings.default_llm_provider and settings.default_llm_model:
        return ProviderRef.parse(settings.default_llm_provider), settings.default_llm_model
    return None


def show_model(settings: Settings, show: Show) -> tuple[ProviderRef, str] | None:
    """The language model a show's own work (ranking, scripts) uses: the show's choice, else the
    instance default; None if neither is set."""
    for provider, model in (
        (show.llm_provider, show.llm_model),
        (settings.default_llm_provider, settings.default_llm_model),
    ):
        if provider and model:
            return ProviderRef.parse(provider), model
    return None
