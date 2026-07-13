#!/usr/bin/env bash
# ExpertSeat — initial setup script
# Run this after cloning the repo to get your local development environment ready.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> ExpertSeat local setup"
echo "    Repo root: $REPO_ROOT"

# Check prerequisites
check_command() {
  if ! command -v "$1" &>/dev/null; then
    echo "ERROR: '$1' is required but not found. Please install it and re-run this script."
    exit 1
  fi
}

echo "==> Checking prerequisites..."
check_command git
check_command node
check_command pnpm
check_command python3
check_command uv
check_command docker

echo "    All prerequisites found."

# Install frontend dependencies
echo "==> Installing frontend dependencies..."
cd "$REPO_ROOT"
pnpm install --frozen-lockfile

# Install backend dependencies
echo "==> Installing backend dependencies..."
cd "$REPO_ROOT/services/api"
uv sync --locked --extra dev

# Copy .env.example if .env doesn't exist
if [ ! -f "$REPO_ROOT/.env" ]; then
  echo "==> Creating .env from .env.example..."
  cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
  echo "    .env created. Edit it with your local values if needed."
else
  echo "==> .env already exists, skipping."
fi

echo ""
echo "==> Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Start infrastructure:    make dev-infra  (from $REPO_ROOT)"
echo "  2. Run migrations:          make migrate"
echo "  3. Start dev servers:       make dev"
echo ""
