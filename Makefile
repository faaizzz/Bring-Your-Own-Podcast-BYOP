.PHONY: check test lint typecheck

# Placeholder targets: story #2 replaces these with the full set (up, down, logs, ...).
check: lint typecheck test

lint:
	@echo "lint: nothing to lint yet"

typecheck:
	@echo "typecheck: nothing to typecheck yet"

test:
	./scripts/check-repo.sh
