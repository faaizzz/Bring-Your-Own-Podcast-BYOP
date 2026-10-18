# Shared by the api, worker and beat services (different `command:` per service).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

RUN useradd --create-home --uid 1000 byop \
    && mkdir -p /app /data/media \
    && chown -R byop:byop /app /data

WORKDIR /app

# Dependencies first so code changes do not invalidate this layer.
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=byop:byop apps/api/ ./
RUN uv sync --frozen --no-dev

USER byop
EXPOSE 8000
CMD ["uvicorn", "byop.main:app", "--host", "0.0.0.0", "--port", "8000"]
