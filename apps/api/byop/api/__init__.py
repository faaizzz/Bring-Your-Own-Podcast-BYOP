from fastapi import APIRouter, Depends

from byop.api import (
    auth,
    connections,
    costs,
    covers,
    dashboard,
    discovery,
    episodes,
    health,
    history,
    integrations,
    models,
    providers,
    runs,
    show_audio,
    shows,
    sources,
    speakers,
    styles,
    user_settings,
    voices,
)
from byop.api.deps import current_user

api_router = APIRouter(prefix="/api")

# Public: health, login/logout, and (in later stories) the RSS feed and episode audio.
api_router.include_router(health.router)
api_router.include_router(auth.public_router)
api_router.include_router(covers.public_router)

# Everything else requires a session. Register new resource routers here so that the
# guard is the default; tests/api/test_guard.py fails if a route escapes it.
protected = APIRouter(dependencies=[Depends(current_user)])
protected.include_router(auth.protected_router)
protected.include_router(integrations.router)
protected.include_router(connections.router)
protected.include_router(providers.router)
protected.include_router(models.router)
protected.include_router(shows.router)
protected.include_router(covers.router)
protected.include_router(show_audio.router)
protected.include_router(sources.router)
protected.include_router(discovery.router)
protected.include_router(speakers.router)
protected.include_router(styles.router)
protected.include_router(episodes.router)
protected.include_router(episodes.show_router)
protected.include_router(dashboard.router)
protected.include_router(costs.router)
protected.include_router(costs.pricing_router)
protected.include_router(history.router)
protected.include_router(runs.router)
protected.include_router(runs.show_router)
protected.include_router(user_settings.router)
protected.include_router(voices.router)
api_router.include_router(protected)
