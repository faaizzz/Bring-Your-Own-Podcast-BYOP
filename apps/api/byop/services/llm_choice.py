from byop.config import Settings
from byop.models import Show
from byop.services.provider_ref import ProviderRef


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
