# Contributing to ExpertSeat

ExpertSeat is a private repository. This document describes the expected workflow for contributors.

---

## Branching

- `main` — stable, CI-passing code. Direct pushes are prohibited.
- `milestone/<N>-<slug>` — the active development branch for a milestone (e.g., `milestone/0-foundation`).
- `feat/<description>` — feature branches off the active milestone branch.
- `fix/<description>` — bug fix branches.
- `chore/<description>` — tooling, dependency, or documentation changes.

All work should happen on a branch. PRs are required to merge to `main`.

---

## Commits

Use the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>: <short description>

[optional body]

[optional footer]
```

Types:
- `feat`: a new feature
- `fix`: a bug fix
- `chore`: tooling, deps, config, or process changes
- `docs`: documentation changes only
- `test`: adding or updating tests
- `refactor`: code restructuring without behavior change
- `ci`: CI/CD changes

Examples:
```
feat: add blueprint CRUD endpoints
fix: correct org isolation filter in candidate query
chore: upgrade Next.js to 14.2.5
docs: document AI provider abstraction in ARCHITECTURE.md
test: add org boundary integration tests
```

---

## Pull Requests

Before opening a PR:

1. Run `make check` locally and ensure all checks pass
2. Update `KNOWN_LIMITATIONS.md` if your change has limitations
3. Update relevant documentation if you've changed behavior
4. Write tests for new functionality

PR description should include:
- **What** was changed (brief summary)
- **Why** it was changed
- **How** to test the change
- Any known limitations or follow-up work

PRs require at least one review before merge (once the team grows beyond one person).

---

## Testing Requirements

- All new features must have unit tests
- All bug fixes must have a regression test
- `make test` must pass
- See [TESTING.md](./TESTING.md) for the full testing strategy

---

## Documentation Requirements

- Architecture changes must be reflected in [ARCHITECTURE.md](./ARCHITECTURE.md)
- New decisions must be added to [DECISIONS.md](./DECISIONS.md)
- New risks must be added to [RISK_REGISTER.md](./RISK_REGISTER.md)
- If a feature is intentionally limited, document it in [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md)

---

## Security

- Never commit `.env` files or any files containing real credentials
- Never commit API keys, passwords, or tokens — even in test files
- Never hardcode production configuration values
- If you discover a security vulnerability, do not create a public issue — contact the repository owner directly
- See [SECURITY.md](./SECURITY.md) for the full security policy

---

## Prohibited Actions

The following are explicitly prohibited:

- Committing to `main` directly
- Adding fake product features, placeholder dashboards, or UI that implies functionality that doesn't exist
- Hardcoding profession-specific logic (ExpertSeat is profession-agnostic — domain knowledge comes from blueprints)
- Using `git push --force` on shared branches
- Skipping CI with `[skip ci]` without team discussion
- Committing generated files (`.next/`, `__pycache__/`, etc.)
- Adding dependencies without reviewing their license and security posture

---

## Code Style

**Python**:
- Formatted with `ruff format` (line length 100)
- Linted with `ruff check`
- Type-checked with `pyright`

**TypeScript**:
- Linted with `eslint`
- Type-checked with `tsc --noEmit`

Run `make format` to auto-format all code before committing.

---

## Dependency Management

- Frontend: add dependencies with `pnpm add [--save-dev] <package>`
- Backend: add dependencies by editing `pyproject.toml` and running `uv sync`
- All lock files must be committed
- Dependabot will open PRs for security updates — review and merge promptly

---

## Questions

If you're unsure about something, open a draft PR or discussion rather than guessing.
