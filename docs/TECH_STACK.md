# Tech Stack

> **Binding contract for autonomous AI coding agents.**
> Do not introduce any library, pattern, service, or tool not listed here without flagging it first in a comment or PR description. Version pins are mandatory; do not silently upgrade or substitute. Items marked **** require human confirmation before the relevant code is merged.

---

## 1. Frontend

| Decision | Choice |
|---|---|
| Framework | React `18.3.1`  — source specifies React; version not given |
| Language | TypeScript `5.5.x`  — TS required for RBAC/role safety; confirm |
| Styling | Tailwind CSS `3.4.x`  — utility-first fits role-scoped dashboard layout |
| Component library | shadcn/ui (headless, Radix-based)  — pairs with Tailwind; confirm or override |
| State management | Zustand `4.x`  — lightweight, no boilerplate; confirm or override |
| Data fetching / server-state | TanStack Query (React Query) `5.x`  — fits REST polling and caching for live dashboards |
| Build tool / bundler | Vite `5.x`  — standard for React/TS; faster than CRA/Webpack |
| Package manager | pnpm `9.x`  — deterministic lockfile; confirm or override with npm/yarn |
| Charts / data visualisation | Recharts `2.x`  — needed for throughput-vs-forecast and quality drift charts |

---

## 2. Backend

| Decision | Choice |
|---|---|
| Language | Python `3.12.x`  — source specifies Python; version not given; 3.12 is current stable |
| Framework | FastAPI `0.111.x`  — source specifies FastAPI; exact version not given |
| ASGI server | Uvicorn `0.30.x`  — standard FastAPI runtime |
| API style | REST (JSON over HTTP) — FastAPI default; no GraphQL or tRPC specified |
| ORM / query layer | SQLAlchemy `2.x` (async) + `asyncpg` driver  — needed for async FastAPI + PostgreSQL; Supabase exposes standard Postgres |
| Validation library | Pydantic `v2` — ships with FastAPI 0.111+; no separate choice needed |
| LLM integration / agent orchestration | **Unspecified in source — see Open Questions** |
| RAG / vector search | **Unspecified in source — see Open Questions** |

---

## 3. Database

| Decision | Choice |
|---|---|
| Engine | PostgreSQL `16.x`  — Supabase currently runs Postgres 15–16; confirm exact managed version |
| Hosting | Supabase managed PostgreSQL — explicitly specified in source |
| Row-Level Security | PostgreSQL RLS — explicitly specified; every table that holds client-scoped or role-scoped data **must** have RLS policies defined |
| Migration tool | Supabase CLI migrations (`supabase/migrations/`)  — native to Supabase; confirm or override with Alembic if backend-driven migrations are preferred |
| Schema naming convention | `snake_case` for all table and column names — PostgreSQL convention; enforced by linter |

---

## 4. Authentication & Authorization

| Decision | Choice |
|---|---|
| Auth provider | Supabase Auth — explicitly specified in source |
| Auth strategy | JWT (issued by Supabase Auth on login); short-lived access token + refresh token |
| Token storage | `httpOnly` cookie  — more secure than `localStorage`; confirm if Supabase client SDK default (`localStorage`) is acceptable instead |
| RBAC enforcement | PostgreSQL Row-Level Security (RLS) policies — explicitly specified in source |
| Identity provider / SSO | None planned — Supabase Auth only; no separate IdP specified |
| Role model | Four roles, each mapped to a Supabase Auth claim and corresponding RLS policy: `client`, `delivery_manager`, `bsg_leadership`, `super_admin` (derived from Section 2, PROJECT_SUMMARY.md) |
| Tenant isolation | RLS on every client-data table; `org_id` or `client_id` foreign key on every scoped row; cross-tenant queries must be impossible at the database layer, not just application layer — hard requirement per source |
| Super Admin scope | Platform-wide configuration only (e.g., which metrics appear on client dashboards); Super Admin bypasses RLS for config tables only, not client data tables  — confirm scope |

---

## 5. Infrastructure & Deployment

| Decision | Choice |
|---|---|
| Cloud provider / hosting | **Unspecified beyond Supabase — see Open Questions** |
| Containerisation | Docker  — standard for FastAPI services; `Dockerfile` per service |
| Container orchestration | **Unspecified — see Open Questions** |
| CI/CD pipeline | GitHub Actions  — most common free-tier choice; confirm or override |
| Environments | `dev` (local), `staging` (sanitised/synthetic data only), `prod` (requires governance sign-off before live client data is connected) |
| Environment promotion | No live client data before explicit client approval, governance sign-off, security validation, and compliance review — hard requirement from source |
| Frontend hosting | Vercel  — integrates natively with Vite/React; confirm or override |
| Backend hosting | **Unspecified — see Open Questions** |
| Data residency | EU & client-region compliant — requirement from source; enforce via Supabase project region selection |

---

## 6. Third-Party Services & External APIs

| Service | Purpose | Config location |
|---|---|---|
| Supabase | Managed PostgreSQL, Auth, RLS, storage | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` in `.env` |
| LLM provider | Powers all six agents (NL query, narrative generation, risk scoring, root-cause analysis, etc.) | **Unspecified — see Open Questions**; config key placeholder: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` |
| Vector database / embedding store | RAG (Retrieval-Augmented Generation) for grounding agent outputs in operational evidence | **Unspecified — see Open Questions**; Supabase `pgvector` extension is a candidate given existing Supabase dependency |
| Email / notification delivery | Alert delivery to PMs and Delivery Managers when risk thresholds are crossed |  — Resend or SendGrid; unspecified in source |

**No other external APIs are specified in the source material.** Agents must not add integrations not listed here.

---

## 7. Dev Tooling

| Tool | Purpose | Version |
|---|---|---|
| ESLint | Frontend linting | `9.x`  |
| Prettier | Frontend + backend code formatting | `3.x`  |
| Ruff | Python linting and formatting (replaces flake8 + black) | `0.5.x`  |
| Mypy | Python static type checking | `1.10.x`  |
| Pytest | Python unit and integration tests | `8.x`  |
| pytest-asyncio | Async test support for FastAPI/asyncpg | `0.23.x`  |
| Vitest | Frontend unit tests (Vite-native) | `2.x`  |
| Playwright | End-to-end tests (role-based UI flows, tenant isolation verification) | `1.45.x`  |
| TypeScript compiler | `tsc --noEmit` run in CI | ships with TypeScript `5.5.x` |
| Pre-commit | Enforces linting/formatting before every commit | `3.x`  |

**Tenant isolation must have dedicated Playwright e2e tests** — a Client user must provably be unable to retrieve another client's data. This is not optional; see success criteria in PROJECT_SUMMARY.md Section 5.

---

## 8. Repository & Folder Structure

Monorepo — one repository, two top-level workspaces (`frontend/` and `backend/`). Rationale: single source of truth for shared types and env var definitions; small team size makes a polyrepo overhead unjustified at this stage.

```
/
├── frontend/                   # React + Vite app
│   ├── src/
│   │   ├── agents/             # One folder per agent (delivery, quality, client-interaction, …)
│   │   ├── components/         # Shared UI components
│   │   ├── hooks/              # Shared custom hooks
│   │   ├── lib/                # Supabase client, API client, utility functions
│   │   ├── pages/              # Route-level page components
│   │   ├── stores/             # Zustand stores
│   │   └── types/              # Shared TypeScript types (mirrors backend schemas)
│   ├── public/
│   ├── index.html
│   ├── vite.config.ts
│   └── package.json
│
├── backend/                    # FastAPI app
│   ├── app/
│   │   ├── agents/             # One module per agent (delivery, quality, client_interaction, …)
│   │   ├── api/                # Route handlers, grouped by agent
│   │   ├── core/               # Config, security, RBAC middleware
│   │   ├── db/                 # SQLAlchemy models, session factory
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   └── services/           # Business logic, LLM orchestration
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
│
├── supabase/
│   ├── migrations/             # SQL migration files (Supabase CLI format)
│   └── seed/                   # Synthetic / sanitised seed data (never real client data)
│
├── e2e/                        # Playwright tests
├── .github/
│   └── workflows/              # CI/CD pipeline definitions
├── .env.example                # Template — no real secrets
├── docker-compose.yml          # Local development stack
└── README.md
```

**Naming conventions:**
- Files and folders: `kebab-case` in frontend, `snake_case` in backend.
- React components: `PascalCase.tsx`.
- Python modules: `snake_case.py`.
- Database tables: `snake_case`, pluralised (e.g., `delivery_projects`, `quality_metrics`).
- Migration files: `{timestamp}_{description}.sql` (Supabase CLI default).

---

## 9. Environment Variables

All secrets are stored in `.env` (local, git-ignored) and in the CI/CD secrets store. `.env.example` contains every key with placeholder values and is committed to the repository.

### Supabase

```
SUPABASE_URL=                    # Supabase project URL (e.g. https://xxx.supabase.co)
SUPABASE_ANON_KEY=               # Public anon key — safe for frontend bundle
SUPABASE_SERVICE_ROLE_KEY=       # Full-access key — backend only, never exposed to frontend
```

### Backend (FastAPI)

```
DATABASE_URL=                    # Full asyncpg connection string (derived from Supabase credentials)
SECRET_KEY=                      # Used for signing internal tokens or session data
ENVIRONMENT=                     # dev | staging | prod
ALLOWED_ORIGINS=                 # CORS allowed origins (comma-separated)
```

### LLM / AI layer

```
LLM_API_KEY=                     # API key for the chosen LLM provider (unspecified — see Open Questions)
LLM_BASE_URL=                    # Base URL for LLM API endpoint
LLM_MODEL=                       # Model identifier string
EMBEDDING_API_KEY=               # If embedding provider differs from LLM provider
```

### Notification / email (if applicable)

```
EMAIL_API_KEY=                   # API key for email delivery service (unspecified — see Open Questions)
EMAIL_FROM_ADDRESS=              # Sender address for system alerts
```

### CI/CD

```
VERCEL_TOKEN=                    # Frontend deployment (if Vercel is confirmed)
DOCKER_REGISTRY_URL=             # Container registry for backend image pushes
```

---

## 10. Rationale for Non-Obvious Choices

**Supabase Auth + PostgreSQL RLS (not a separate IdP or application-layer RBAC):**
Enforcing tenant isolation and RBAC at the database layer via RLS means even a buggy API route cannot leak cross-tenant data — the database itself refuses the query. This is the primary security requirement of the project and the choice is explicitly specified in the source.

**Monorepo:**
Single team, tightly coupled frontend/backend contracts, shared type definitions between React and FastAPI Pydantic schemas. A polyrepo would introduce synchronisation overhead that isn't warranted at this scale.

**REST (not GraphQL or tRPC):**
FastAPI's OpenAPI-first REST is the natural default for a Python backend; tRPC requires TypeScript on both sides; GraphQL adds schema maintenance overhead. None of the more complex alternatives are justified by the data access patterns described in the source (role-scoped reads, admin configuration writes, agent query responses).

**Ruff (not flake8 + black separately):**
Ruff replaces both at 10–100× the speed, has no conflicting config surface, and is now the de facto Python linting standard. Keeping the tool count low matters for autonomous agent use.

**Synthetic/sanitised data in all non-prod environments:**
Hard requirement from the source: the build and test environment must never contain live client production data prior to explicit governance and security sign-off. Seed scripts must only contain fabricated or anonymised operational data.

**`httpOnly` cookie for JWT storage:**
Storing tokens in `localStorage` exposes them to XSS. Given the sensitivity of client delivery data and the regulated-domain clients (Life Sciences, Finance), `httpOnly` cookies are the safer default. Override only if the Supabase client SDK imposes a constraint.

---

## 11. Open Questions

All items marked **** above are collected here. Each must be confirmed or overridden by a human before the relevant code is merged.

| # | Item | What needs deciding |
|---|---|---|
| 1 | React version | Confirm `18.3.1` or specify a different pin |
| 2 | TypeScript | Confirm TS as the frontend language (vs plain JS); confirm `5.5.x` pin |
| 3 | Tailwind CSS | Confirm as styling solution, or specify an alternative |
| 4 | shadcn/ui | Confirm as component library, or specify an alternative |
| 5 | Zustand | Confirm for state management, or specify Redux Toolkit / Jotai / Context API |
| 6 | TanStack Query | Confirm for server-state / data fetching |
| 7 | Vite | Confirm as bundler, or specify Next.js (which would change folder structure) |
| 8 | pnpm | Confirm as package manager, or specify npm/yarn |
| 9 | Recharts | Confirm for charting, or specify D3 / Chart.js / Nivo |
| 10 | Python `3.12.x` | Confirm version pin |
| 11 | FastAPI `0.111.x` | Confirm version pin |
| 12 | SQLAlchemy async + asyncpg | Confirm ORM/driver choice, or specify Tortoise ORM / raw asyncpg / Supabase Python client only |
| 13 | **LLM provider** | Unspecified in source — must decide vendor (OpenAI, Anthropic, Azure OpenAI, self-hosted, etc.) and model before any agent code can be written |
| 14 | **Vector database / RAG layer** | Unspecified — Supabase `pgvector` is a low-overhead candidate given existing Supabase dependency; alternatives: Pinecone, Weaviate, Qdrant |
| 15 | PostgreSQL version | Confirm exact Supabase-managed Postgres version (`15.x` or `16.x`) |
| 16 | Migration tooling | Confirm Supabase CLI migrations, or switch to Alembic (backend-driven) |
| 17 | JWT token storage | Confirm `httpOnly` cookie vs Supabase SDK default (`localStorage`) |
| 18 | Super Admin RLS scope | Confirm that Super Admin bypasses RLS only for platform-config tables, not for client data tables |
| 19 | **Cloud hosting provider** (beyond Supabase) | Unspecified — where does the FastAPI backend container run? (Railway, Fly.io, AWS ECS, GCP Cloud Run, etc.) |
| 20 | Container orchestration | Confirm Docker only (single container per service), or Kubernetes / Docker Swarm |
| 21 | CI/CD platform | Confirm GitHub Actions, or specify GitLab CI / Bitbucket Pipelines |
| 22 | Frontend hosting | Confirm Vercel, or specify Netlify / self-hosted |
| 23 | Email / notification service | Unspecified — confirm Resend, SendGrid, AWS SES, or none for MVP |
| 24 | ESLint / Prettier / Ruff versions | Confirm all tooling version pins, or defer until scaffold is generated |
| 25 | **Build vs. partner decision** | Source leaves open whether the analytics/agent layer is built in-house or via a third-party partner (Arbios named as example); this has direct implications for Section 6 (third-party services) |
| 26 | **Pilot client and vertical** | Must be decided before production data wiring begins; affects which domain-specific data schemas and seed data are built first |
