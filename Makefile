.PHONY: setup dev-infra dev-infra-wait dev format format-check lint typecheck test \
        migrate migrate-down migrate-up migrate-full build check secret-scan \
        infra-validate audit clean stop

COMPOSE := docker compose -f infrastructure/docker-compose.yml
API_DIR  := services/api
WEB_DIR  := apps/web

# ─── Setup ──────────────────────────────────────────────────────────────────

# Install all dependencies (run once after clone)
setup:
	pnpm install --frozen-lockfile
	cd $(API_DIR) && uv sync --locked --extra dev

# ─── Infrastructure ──────────────────────────────────────────────────────────

# Start PostgreSQL and Redis in the background
dev-infra:
	$(COMPOSE) up -d

# Wait until both services are healthy before proceeding (60-second timeout)
dev-infra-wait: dev-infra
	@echo "Waiting for PostgreSQL (timeout: 60s)..."
	@DEADLINE=$$(( $$(date +%s) + 60 )); \
	 until docker inspect --format='{{.State.Health.Status}}' $$($(COMPOSE) ps -q postgres) 2>/dev/null | grep -q healthy; do \
	   [ $$(date +%s) -lt $${DEADLINE} ] || { echo "ERROR: PostgreSQL did not become healthy within 60s"; exit 1; }; \
	   sleep 1; \
	 done
	@echo "Waiting for Redis (timeout: 60s)..."
	@DEADLINE=$$(( $$(date +%s) + 60 )); \
	 until docker inspect --format='{{.State.Health.Status}}' $$($(COMPOSE) ps -q redis) 2>/dev/null | grep -q healthy; do \
	   [ $$(date +%s) -lt $${DEADLINE} ] || { echo "ERROR: Redis did not become healthy within 60s"; exit 1; }; \
	   sleep 1; \
	 done
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
# Full gate: versions, static analysis, infrastructure, runtime
# (including degradation/recovery), and security scans.
# Run with: make check
# Requires: Docker running, Node.js 24, pnpm 11.12.0, Python 3.12, uv 0.11.7, gitleaks 8.30.1.
# Delegates to scripts/check_all.sh → check_infrastructure.sh → check_migrations.sh.
# Migration logic exists only in check_migrations.sh (used by both the runtime path
# and the dedicated CI migrations job).
check:
	scripts/check_all.sh

# ─── Clean up ────────────────────────────────────────────────────────────────

clean:
	$(COMPOSE) down -v 2>/dev/null || true
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .next -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.tsbuildinfo" -delete 2>/dev/null || true
