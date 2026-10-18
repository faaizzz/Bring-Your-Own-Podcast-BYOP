.DEFAULT_GOAL := help
.PHONY: help up up-kokoro down logs migrate deps test lint typecheck check fmt

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

down: ## Stop the stack (keeps volumes)
	$(COMPOSE) --profile kokoro down

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
