from fastapi import APIRouter, Depends

from byop.api import auth, health, integrations, models, shows, voices
from byop.api.deps import current_user

api_router = APIRouter(prefix="/api")

# Public: health, login/logout, and (in later stories) the RSS feed and episode audio.
api_router.include_router(health.router)
api_router.include_router(auth.public_router)

# Everything else requires a session. Register new resource routers here so that the
# guard is the default; tests/api/test_guard.py fails if a route escapes it.
protected = APIRouter(dependencies=[Depends(current_user)])
protected.include_router(auth.protected_router)
protected.include_router(integrations.router)
protected.include_router(models.router)
protected.include_router(shows.router)
protected.include_router(voices.router)
api_router.include_router(protected)
