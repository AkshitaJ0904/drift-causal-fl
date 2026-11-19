"""Tests for bounded PostgreSQL connection and statement waits."""

from types import SimpleNamespace

from core.supabase import connection


def test_database_engine_sets_connection_and_statement_timeouts(monkeypatch) -> None:
    calls = {}
    expected_engine = object()

    def fake_create_engine(database_url, **kwargs):
        calls["database_url"] = database_url
        calls["kwargs"] = kwargs
        return expected_engine

    monkeypatch.setattr(
        connection,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql+psycopg://test/db"),
    )
    monkeypatch.setattr(connection, "create_engine", fake_create_engine)

    result = connection.create_database_engine()

    assert result is expected_engine
    assert calls["kwargs"]["connect_args"] == {
        "connect_timeout": 5,
        "options": "-c statement_timeout=30000",
    }
    assert calls["kwargs"]["pool_timeout"] == 30
