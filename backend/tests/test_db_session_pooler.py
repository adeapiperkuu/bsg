import logging

from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from app.db import session as db_session


def test_database_url_classification_for_supabase_poolers_and_direct_postgres() -> None:
    assert (
        db_session.classify_database_url(
            "postgresql+asyncpg://postgres:secret@aws-0-eu.pooler.supabase.com:6543/postgres"
        )
        == "supabase_transaction_pooler"
    )
    assert (
        db_session.classify_database_url(
            "postgresql+asyncpg://postgres:secret@aws-0-eu.pooler.supabase.com:5432/postgres"
        )
        == "supabase_session_pooler"
    )
    assert (
        db_session.classify_database_url("postgresql+asyncpg://postgres:secret@localhost:5432/postgres")
        == "direct_postgres"
    )


def test_transaction_pooler_uses_client_pool_and_disables_prepared_statement_caches() -> None:
    kwargs = db_session._engine_kwargs(
        "postgresql+asyncpg://postgres:secret@aws-0-eu.pooler.supabase.com:6543/postgres"
    )

    assert kwargs["poolclass"] is AsyncAdaptedQueuePool
    assert kwargs["pool_size"] == 10
    assert kwargs["max_overflow"] == 10
    assert kwargs["pool_recycle"] == 900
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["connect_args"]["statement_cache_size"] == 0
    assert kwargs["connect_args"]["prepared_statement_cache_size"] == 0
    assert "prepared_statement_name_func" in kwargs["connect_args"]


def test_session_pooler_warning_does_not_log_database_url_or_password(caplog) -> None:
    database_url = "postgresql+asyncpg://postgres:super-secret@aws-0-eu.pooler.supabase.com:5432/postgres"

    with caplog.at_level(logging.WARNING):
        kwargs = db_session._engine_kwargs(database_url)

    assert kwargs["poolclass"] is NullPool
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "session pooler" in messages.lower()
    assert "super-secret" not in messages
    assert database_url not in messages
