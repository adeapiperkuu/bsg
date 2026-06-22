# BSG Operations Tower Backend

FastAPI service scaffold aligned with `docs/08. Backend Architecture.md`.

## Structure

- `app/main.py` creates the FastAPI app, registers CORS, exception handlers, and route groups.
- `app/core/` contains settings, auth/JWT helpers, and standard API errors.
- `app/db/` contains the async SQLAlchemy session and ORM models mirroring `docs/10. DB Schema.md`.
- `app/api/routes/` contains versioned REST route groups under `/api/v1`.
- `app/services/` contains business rules such as tenant scoping, evidence enforcement, ingestion, and communication approval gates.
- `app/agents/` contains Phase-1 agent entry points and domain logic placeholders.

## Local Setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
uvicorn app.main:app --reload
```

Local development should start the FastAPI app directly with Python/Uvicorn. Docker is intentionally reserved for deployment packaging, not for starting the project during development.

The Supabase migration scaffold lives in `../supabase/migrations/`, and initial metric seed data lives in `../supabase/seed/`.

## Deployment

`Dockerfile` is present only as the backend container build artifact for deployment environments.
