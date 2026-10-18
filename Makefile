.DEFAULT_GOAL := help
.PHONY: help up up-kokoro up-minio up-langfuse e2e e2e-down down logs migrate deps test lint typecheck check fmt

COMPOSE ?= docker compose
API_DIR := apps/api
WEB_DIR := apps/web

help: ## Show available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

up: ## Build and start the whole stack, wait until healthy
	./scripts/ensure-env.sh
	$(COMPOSE) up -d --build --wait

up-kokoro: ## Like `up`, plus the local Kokoro text-to-speech service
	./scripts/ensure-env.sh
	$(COMPOSE) --profile kokoro up -d --build --wait

up-minio: ## Like `up`, plus a local S3-compatible object store (see docs/storage.md)
	./scripts/ensure-env.sh
	$(COMPOSE) --profile minio up -d --build --wait

up-langfuse: ## Like `up`, plus self-hosted Langfuse tracing (see docs/langfuse.md)
	./scripts/ensure-env.sh
	$(COMPOSE) --profile langfuse up -d --build --wait

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

down: ## Stop the stack (keeps volumes)
	$(COMPOSE) --profile kokoro --profile minio down

logs: ## Follow logs of all services
	$(COMPOSE) logs -f --tail=100

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
