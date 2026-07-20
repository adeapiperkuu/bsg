from sqlalchemy.pool import NullPool

from app.db.session import _engine_kwargs, _is_supabase_pooler, _is_transaction_pooler


def test_supabase_session_pooler_uses_null_pool() -> None:
    url = "postgresql+asyncpg://user:pass@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
    assert _is_supabase_pooler(url)
    assert not _is_transaction_pooler(url)

    kwargs = _engine_kwargs(url)
    assert kwargs["poolclass"] is NullPool
    assert "pool_size" not in kwargs


def test_supabase_transaction_pooler_uses_persistent_pool_and_disables_statement_cache() -> None:
    """Phase 1A (docs/PERF_IMPLEMENTATION_PLAN.md): the transaction pooler
    (port 6543) branch switched from `NullPool` (a fresh connection per
    request, ~1s fixed tax, zero reuse) to a real, persistent client-side
    pool -- safe here specifically because the asyncpg/SQLAlchemy
    prepared-statement caches are disabled below, so a reused connection
    never risks a stale prepared statement against PgBouncer transaction
    mode."""
    url = "postgresql+asyncpg://user:pass@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
    assert _is_supabase_pooler(url)
    assert _is_transaction_pooler(url)

    kwargs = _engine_kwargs(url)
    assert "poolclass" not in kwargs, "transaction pooler should use SQLAlchemy's default persistent pool, not NullPool"
    assert kwargs["pool_size"] == 10
    assert kwargs["max_overflow"] == 10
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] == 1800
    assert kwargs["connect_args"]["statement_cache_size"] == 0
    assert kwargs["connect_args"]["prepared_statement_cache_size"] == 0


def test_local_postgres_keeps_default_pool() -> None:
    url = "postgresql+asyncpg://user:pass@127.0.0.1:5432/bsg"
    assert not _is_supabase_pooler(url)

    kwargs = _engine_kwargs(url)
    assert kwargs.get("pool_pre_ping") is True
    assert "poolclass" not in kwargs
