# FastAPI backend for the BSG Operations Tower

FastAPI service aligned with `docs/08. Backend Architecture.md` and `docs/09. API Specification.md`.

## Structure

- `app/main.py` — FastAPI app, CORS, CSRF middleware, route groups
- `app/core/` — settings, JWT/cookie auth, CSRF, permissions
- `app/api/routes/auth.py` — httpOnly cookie BFF (`/auth/login`, `/auth/refresh`, `/auth/logout`)
- `app/db/` — async SQLAlchemy session, ORM models, RLS context helper
- `app/services/` — user provisioning, Supabase Auth client, tenant scoping
- `supabase/migrations/` — schema + RLS policies

## Authentication (httpOnly cookie BFF)

1. Frontend posts credentials to `POST /api/v1/auth/login`.
2. Backend exchanges them with Supabase Auth and sets `access_token`, `refresh_token`, and `csrf_token` cookies.
3. Browser sends cookies on subsequent requests (`credentials: include`).
4. Mutating requests must include `X-CSRF-Token` matching the readable `csrf_token` cookie.
5. `GET /api/v1/me` returns role, organisation, and permission flags for UI routing.

Bearer tokens in the `Authorization` header are still supported for scripts and tests.

## Environment variables

Copy `../.env.example` to `../.env` and set:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL (`postgresql+asyncpg://…` for the backend) |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Anon key (login token exchange) |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role (user provisioning) |
| `SUPABASE_JWT_SECRET` | JWT secret from Supabase dashboard (HS256) or JWKS URL |
| `SECRET_KEY` | CSRF/session signing fallback in dev |
| `AUTH_COOKIE_SECURE` | `false` locally, `true` in staging/prod |
| `ALLOWED_ORIGINS` | Comma-separated frontend origins (required for cookies) |

## Bootstrap first super_admin

```powershell
cd backend
.venv\Scripts\Activate
python ../scripts/bootstrap_super_admin.py --email admin@example.com --password "YourSecurePassword!"
```

This creates the Supabase Auth user and matching `public.users` row with `role = super_admin`.

## Dev login accounts

For local development, seed three quick-login users (admin, PM, client):

```powershell
cd backend
.venv\Scripts\Activate
python ../scripts/seed_dev_users.py
```

| Role | Email | Password |
|---|---|---|
| Admin (`super_admin`) | `admin@bsg.dev` | `bsg-dev-2026` |
| PM (`delivery_manager`) | `pm@bsg.dev` | `bsg-dev-2026` |
| Client (`client`) | `client@bsg.dev` | `bsg-dev-2026` |

The login page shows these accounts in development mode only.

Disable public sign-up in the Supabase dashboard (Authentication → Providers).

## RLS note

RLS policies are defined in `supabase/migrations/20260623100000_rls_policies.sql`. The backend sets `request.jwt.claims` per authenticated request. Connections using the Postgres superuser role bypass RLS; use a non-superuser pool role in production if policies must enforce at the database layer.

## Local setup

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Tests

```powershell
cd backend
pytest
```
