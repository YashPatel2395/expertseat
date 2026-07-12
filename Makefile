.PHONY: setup dev-infra dev format lint typecheck test migrate build check clean

# Install all dependencies
setup:
	cd apps/web && pnpm install
	cd services/api && uv sync --extra dev

# Start infrastructure services (postgres + redis)
dev-infra:
	docker compose -f infrastructure/docker-compose.yml up -d

# Development instructions
dev:
	@echo "Run the following commands in separate terminals:"
	@echo "  Terminal 1 (infra):    make dev-infra"
	@echo "  Terminal 2 (api):      cd services/api && uv run uvicorn app.main:app --reload --port 8000"
	@echo "  Terminal 3 (frontend): cd apps/web && pnpm dev"

# Format code
format:
	cd services/api && uv run ruff format .
	cd apps/web && pnpm prettier --write .

# Lint code
lint:
	cd services/api && uv run ruff check .
	cd apps/web && pnpm eslint .

# Type checking
typecheck:
	cd services/api && uv run pyright
	cd apps/web && pnpm tsc --noEmit

# Run tests
test:
	cd services/api && uv run pytest
	cd apps/web && pnpm test

# Run database migrations
migrate:
	cd services/api && uv run alembic upgrade head

# Build frontend
build:
	cd apps/web && pnpm build

# Full quality gate
check: lint typecheck test build

# Clean up
clean:
	docker compose -f infrastructure/docker-compose.yml down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .next -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.tsbuildinfo" -delete 2>/dev/null || true
