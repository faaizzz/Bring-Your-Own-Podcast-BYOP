.DEFAULT_GOAL := help
.PHONY: help up up-full up-kokoro up-minio up-langfuse screenshots build build-full e2e e2e-down down down-v logs logs-full migrate deps test lint typecheck check fmt

COMPOSE ?= docker compose
API_DIR := apps/api
WEB_DIR := apps/web

# Optional services of the full stack, as compose profiles. Override to pick some:
#   BYOP_PROFILES="kokoro" make up-full
BYOP_PROFILES ?= kokoro langfuse minio

# `--profile a --profile b` for a list of profiles.
profile_flags = $(foreach p,$(1),--profile $(p))
# Kokoro is only "configured" when its server is part of the stack; compose reads this default
# when KOKORO_BASE_URL is not set in .env (see docker-compose.yml).
kokoro_url = $(if $(filter kokoro,$(1)),BYOP_BUNDLED_KOKORO_URL=http://kokoro:8880/v1)

help: ## Show available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

up: ## Build and start the minimal stack (api, worker, beat, web, postgres, redis), wait until healthy
	./scripts/ensure-env.sh
	$(COMPOSE) up -d --build --wait

up-full: ## Minimal stack plus local voices (kokoro), tracing (langfuse) and S3 (minio); see BYOP_PROFILES
	./scripts/ensure-env.sh
	$(call kokoro_url,$(BYOP_PROFILES)) $(COMPOSE) $(call profile_flags,$(BYOP_PROFILES)) up -d --build --wait

up-kokoro: ## Alias: minimal stack plus the local Kokoro text-to-speech service
	$(MAKE) up-full BYOP_PROFILES=kokoro

up-minio: ## Alias: minimal stack plus a local S3-compatible object store (see docs/storage.md)
	$(MAKE) up-full BYOP_PROFILES=minio

up-langfuse: ## Alias: minimal stack plus self-hosted Langfuse tracing (see docs/langfuse.md)
	$(MAKE) up-full BYOP_PROFILES=langfuse

build: ## Build the images of the minimal stack
	$(COMPOSE) build

build-full: ## Build/pull the images of the full stack (see BYOP_PROFILES)
	$(COMPOSE) $(call profile_flags,$(BYOP_PROFILES)) build
	$(COMPOSE) $(call profile_flags,$(BYOP_PROFILES)) pull --ignore-buildable

# The end-to-end stack is its own compose project on its own port, so it never touches your data.
E2E_PORT ?= 18080
E2E_COMPOSE = COMPOSE_PROJECT_NAME=byop-e2e BYOP_WEB_PORT=$(E2E_PORT) $(COMPOSE) -f docker-compose.yml -f docker-compose.e2e.yml

e2e: ## Run the browser end-to-end test against a throwaway stack with mock model/voice servers
	$(E2E_COMPOSE) down -v
	$(E2E_COMPOSE) up -d --build --wait
	cd tests/e2e && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npx playwright install --with-deps chromium >/dev/null 2>&1 || true
	cd tests/e2e && E2E_BASE_URL=http://localhost:$(E2E_PORT) npx playwright test; status=$$?; $(E2E_COMPOSE) down -v; exit $$status

e2e-down: ## Remove the end-to-end stack and its data
	$(E2E_COMPOSE) down -v

screenshots: ## Regenerate the pictures in docs/images from a throwaway stack with demo data
	$(E2E_COMPOSE) down -v
	$(E2E_COMPOSE) up -d --build --wait
	cd tests/e2e && { [ -d node_modules/sharp ] || npm install --no-audit --no-fund; } && npx playwright install --with-deps chromium >/dev/null 2>&1 || true
	cd tests/e2e && E2E_BASE_URL=http://localhost:$(E2E_PORT) E2E_SCREENSHOTS=$(CURDIR)/docs/images npx playwright test screenshots.spec.ts; status=$$?; \
		[ $$status -ne 0 ] || node optimize-images.mjs $(CURDIR)/docs/images; $(E2E_COMPOSE) down -v; exit $$status

down: ## Stop and remove every BYOP container, whichever profile started it (keeps volumes)
	$(COMPOSE) --profile '*' down

down-v: ## Like `down`, but also deletes the volumes: database, media, Langfuse data
	@echo "WARNING: this deletes ALL BYOP data (database, media, Langfuse). Press Ctrl-C within 5 s to abort."
	@sleep 5
	$(COMPOSE) --profile '*' down -v

logs: ## Follow logs of the minimal stack
	$(COMPOSE) logs -f --tail=100

logs-full: ## Follow logs of every service of the full stack (see BYOP_PROFILES)
	$(COMPOSE) $(call profile_flags,$(BYOP_PROFILES)) logs -f --tail=100

migrate: ## Apply database migrations
	@if [ -f $(API_DIR)/alembic.ini ]; then \
		$(COMPOSE) run --rm api alembic upgrade head; \
	else \
		echo "migrate: no migrations yet"; \
	fi

lint: ## Lint api and web
	cd $(API_DIR) && uv run ruff check . && uv run ruff format --check .
	cd $(WEB_DIR) && { [ -d node_modules ] || npm ci --silent --no-audit --no-fund; } && npm run lint --silent

typecheck: ## Typecheck api and web
	cd $(API_DIR) && uv run mypy
	cd $(WEB_DIR) && npm run typecheck --silent

deps: ## Start only postgres and redis (used by the api tests)
	./scripts/ensure-env.sh
	$(COMPOSE) up -d --wait postgres redis

test: deps ## Run repo checks, api tests and web tests
	./scripts/check-repo.sh
	cd $(API_DIR) && uv run pytest -q
	cd $(WEB_DIR) && npm test --silent
	cd $(WEB_DIR) && npm run build --silent

check: lint typecheck test ## lint + typecheck + test

fmt: ## Format code
	cd $(API_DIR) && uv run ruff check --fix . && uv run ruff format .
	cd $(WEB_DIR) && npm run format --silent
