# ExpertSeat — Web Frontend

Next.js 16 frontend for ExpertSeat. See the repository root [README.md](../../README.md) for full setup instructions.

## Local development

```bash
# From repository root
pnpm install
pnpm run --filter web dev
```

Frontend available at http://localhost:3000.

## Commands

| Command                              | Purpose                  |
| ------------------------------------ | ------------------------ |
| `pnpm run --filter web dev`          | Start development server |
| `pnpm run --filter web build`        | Production build         |
| `pnpm run --filter web lint`         | ESLint                   |
| `pnpm run --filter web format:check` | Prettier format check    |
| `pnpm run --filter web typecheck`    | TypeScript type check    |
| `pnpm run --filter web test`         | Run Vitest tests         |

## Stack

- Next.js 16.2.10 (App Router)
- React 19
- TypeScript 5
- Tailwind CSS 4
- Vitest + Testing Library
