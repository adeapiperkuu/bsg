# bsg
# BSG Operations Tower

Operations Tower is a role-scoped operations platform for BSG teams and client
users. The repository contains:

- `backend/` — Python 3.12, FastAPI, SQLAlchemy, and async PostgreSQL services
- `frontend/` — React 19, TypeScript, Vite, TanStack Router, and Vitest
- `supabase/migrations/` — PostgreSQL schema and row-level-security migrations
- `docs/` — product, architecture, security, agent, and delivery documentation

## Local setup

Copy `backend/.env.example` to `backend/.env` and provide development-safe
values. Do not commit the resulting `.env` file.

Backend:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend, in a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

## Verification

The default verification path is intentionally database-safe:

```powershell
python scripts/check_migration_versions.py
cd backend
pytest -q
cd ..\frontend
npm test
npm run build
```

The live RLS suite is opt-in because it connects to a configured PostgreSQL
environment. Run `pytest --run-live-rls` only against an explicitly authorized
database; its test writes are transactionally rolled back.

Pull requests and pushes to `main` and `governane-latency` run the migration
guard, backend tests, frontend tests, and production frontend build through
GitHub Actions. Lint and static type-check debt are not yet CI gates.

## Known repository risks

- [BUG-009](docs/18.%20Known%20Bugs.md#bug-009-live-database-has-13-tables-with-no-corresponding-repository-migration)
  tracks live database tables that are absent from repository migrations.
- Eight historical migration timestamps are duplicated. The migration guard
  prevents new duplicate groups while the deployed migration history is
  reconciled; do not rename applied migrations without that reconciliation.
- Product-level agent gaps remain tracked in each
  `backend/app/agents/*_V1_GAPS.md` file.

See [backend/README.md](backend/README.md) for authentication, environment, and
backend-specific operating details.
