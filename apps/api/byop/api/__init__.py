from fastapi import APIRouter

from byop.api import health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
