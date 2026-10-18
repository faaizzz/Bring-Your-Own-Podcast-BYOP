import os

from celery import Celery

celery_app = Celery("byop", broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
