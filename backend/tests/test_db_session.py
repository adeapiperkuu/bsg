from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from app.db.session import _engine_kwargs, _is_supabase_pooler, _is_transaction_pooler


def test_supabase_session_pooler_uses_null_pool() -> None:
    url = "postgresql+asyncpg://user:pass@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
    assert _is_supabase_pooler(url)
    assert not _is_transaction_pooler(url)

    kwargs = _engine_kwargs(url)
    assert kwargs["poolclass"] is NullPool
    assert "pool_size" not in kwargs


def test_supabase_transaction_pooler_reuses_connections_and_disables_statement_cache() -> None:
    """The transaction pooler path must pool client connections, not discard them.

    It previously used NullPool, which reopened a TCP+TLS+auth handshake per request —
    measured at ~1.5s against a remote Supabase pooler, i.e. the dominant cost of every
    request. Connection reuse is safe here only because the prepared-statement caches are
    disabled and statement names are unique per prepare(), so the two are asserted together:
    reintroducing a statement cache while pooling would resurrect the stale-statement bug
    NullPool was originally guarding against.
    """
    url = "postgresql+asyncpg://user:pass@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
    assert _is_supabase_pooler(url)
    assert _is_transaction_pooler(url)

    kwargs = _engine_kwargs(url)
    assert kwargs["poolclass"] is AsyncAdaptedQueuePool
    assert kwargs["poolclass"] is not NullPool
    # Must clear the dashboard's 5-way parallel section fan-out without queuing.
    assert kwargs["pool_size"] >= 5
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["connect_args"]["statement_cache_size"] == 0
    assert kwargs["connect_args"]["prepared_statement_cache_size"] == 0


def test_local_postgres_keeps_default_pool() -> None:
    url = "postgresql+asyncpg://user:pass@127.0.0.1:5432/bsg"
    assert not _is_supabase_pooler(url)

    kwargs = _engine_kwargs(url)
    assert kwargs.get("pool_pre_ping") is True
    assert "poolclass" not in kwargs
