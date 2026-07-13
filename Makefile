.PHONY: setup dev-infra dev-infra-wait dev format format-check lint typecheck test \
        migrate migrate-down migrate-up migrate-full build check secret-scan \
        infra-validate audit clean stop

COMPOSE := docker compose -f infrastructure/docker-compose.yml
API_DIR  := services/api
WEB_DIR  := apps/web

# ─── Setup ──────────────────────────────────────────────────────────────────

# Install all dependencies (run once after clone)
setup:
	pnpm install
	cd $(API_DIR) && uv sync --extra dev

# ─── Infrastructure ──────────────────────────────────────────────────────────

# Start PostgreSQL and Redis in the background
dev-infra:
	$(COMPOSE) up -d

# Wait until both services are healthy before proceeding
dev-infra-wait: dev-infra
	@echo "Waiting for PostgreSQL..."
	@until docker inspect --format='{{.State.Health.Status}}' $$($(COMPOSE) ps -q postgres) 2>/dev/null | grep -q healthy; do sleep 1; done
	@echo "Waiting for Redis..."
	@until docker inspect --format='{{.State.Health.Status}}' $$($(COMPOSE) ps -q redis) 2>/dev/null | grep -q healthy; do sleep 1; done
	@echo "Infrastructure ready."

# Stop infrastructure services
stop:
	$(COMPOSE) down

# ─── Development ─────────────────────────────────────────────────────────────

dev:
	@echo "Run each command in a separate terminal:"
	@echo "  Terminal 1 (infra):    make dev-infra"
	@echo "  Terminal 2 (api):      cd $(API_DIR) && uv run uvicorn app.main:app --reload --port 8000"
	@echo "  Terminal 3 (frontend): pnpm run --filter web dev"

# ─── Code quality ────────────────────────────────────────────────────────────

format:
	cd $(API_DIR) && uv run ruff format .
	pnpm run --filter web format

format-check:
	cd $(API_DIR) && uv run ruff format --check .
	pnpm run --filter web format:check

lint:
	cd $(API_DIR) && uv run ruff check .
	pnpm run --filter web lint

typecheck:
	cd $(API_DIR) && uv run pyright
	pnpm run --filter web typecheck

# ─── Tests ───────────────────────────────────────────────────────────────────

test:
	cd $(API_DIR) && uv run pytest -v
	pnpm run --filter web test

# ─── Database migrations ─────────────────────────────────────────────────────

migrate:
	cd $(API_DIR) && uv run alembic upgrade head

migrate-down:
	cd $(API_DIR) && uv run alembic downgrade base

migrate-full: migrate migrate-down migrate
	@echo "Migration cycle (upgrade → downgrade → upgrade) complete."

# ─── Build ───────────────────────────────────────────────────────────────────

build:
	pnpm run --filter web build

# ─── Validation ──────────────────────────────────────────────────────────────

# Validate Docker Compose configuration (no services started)
infra-validate:
	$(COMPOSE) config --quiet

# Run Gitleaks secret scan against full git history (requires gitleaks installed)
secret-scan:
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks detect --source . --log-level warn; \
	else \
		echo "ERROR: gitleaks is not installed. Install via: brew install gitleaks"; \
		exit 1; \
	fi

# Run dependency vulnerability audits for both frontend and backend
audit:
	@echo "=== Python dependency audit ==="
	cd $(API_DIR) && uv run pip-audit
	@echo "=== npm dependency audit (high+critical only) ==="
	pnpm audit --audit-level high

# ─── Full quality gate ───────────────────────────────────────────────────────
# Every step must pass. A failure anywhere halts the gate.
# Run with: make check
# Requires: Docker running, infrastructure started (make dev-infra-wait).
# CI equivalent: each step runs as a separate job.
check:
	@echo "=== [1/14] Validate Docker Compose configuration ==="
	$(MAKE) infra-validate
	@echo "=== [2/14] pnpm install (frozen) ==="
	pnpm install --frozen-lockfile
	@echo "=== [3/14] Backend format check ==="
	cd $(API_DIR) && uv run ruff format --check .
	@echo "=== [4/14] Frontend format check ==="
	pnpm run --filter web format:check
	@echo "=== [5/14] Backend lint ==="
	cd $(API_DIR) && uv run ruff check .
	@echo "=== [6/14] Frontend lint ==="
	pnpm run --filter web lint
	@echo "=== [7/14] Backend type check ==="
	cd $(API_DIR) && uv run pyright
	@echo "=== [8/14] Frontend type check ==="
	pnpm run --filter web typecheck
	@echo "=== [9/14] Backend tests ==="
	cd $(API_DIR) && uv run pytest -v
	@echo "=== [10/14] Frontend tests ==="
	pnpm run --filter web test
	@echo "=== [11/14] Frontend production build ==="
	pnpm run --filter web build
	@echo "=== [12/14] Database migration cycle (upgrade → downgrade → upgrade) ==="
	$(MAKE) migrate-full
	@echo "=== [13/14] Backend API startup validation ==="
	cd $(API_DIR) && uv run python -c "from app.main import app; print('API startup OK')"
	@echo "=== [14/14] Dependency vulnerability audit ==="
	$(MAKE) audit
	@echo ""
	@echo "All quality gate checks passed."

# ─── Clean up ────────────────────────────────────────────────────────────────

clean:
	$(COMPOSE) down -v 2>/dev/null || true
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .next -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.tsbuildinfo" -delete 2>/dev/null || true
