"""Unit tests for PostgreSQL migration verification safety guards."""

import sys

import pytest

import scripts.verify_postgres_migration as migration_verifier
from scripts.verify_postgres_migration import (
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    OPT_IN_VALUE,
    OPT_IN_VARIABLE,
    SafetyCheckError,
    validate_environment,
)


def valid_test_environment() -> dict[str, str]:
    return {
        "DB_USER": EXPECTED_ROLE,
        "DB_PASSWORD": "test-only-secret",
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "5432",
        "DB_NAME": EXPECTED_DATABASE,
        OPT_IN_VARIABLE: OPT_IN_VALUE,
    }


def test_accepts_only_explicit_loopback_disposable_database_config():
    config = validate_environment(valid_test_environment())

    assert config.name == EXPECTED_DATABASE
    assert config.user == EXPECTED_ROLE
    assert config.host == "127.0.0.1"
    assert config.port == 5432


@pytest.mark.parametrize("host", ["db.example.com", "192.0.2.10", "10.0.0.4"])
def test_rejects_remote_database_hosts(host: str):
    values = valid_test_environment()
    values["DB_HOST"] = host

    with pytest.raises(SafetyCheckError, match="DB_HOST"):
        validate_environment(values)


def test_rejects_non_test_database_or_role():
    values = valid_test_environment()
    values["DB_NAME"] = "postgres"
    with pytest.raises(SafetyCheckError, match="DB_NAME"):
        validate_environment(values)

    values = valid_test_environment()
    values["DB_USER"] = "postgres"
    with pytest.raises(SafetyCheckError, match="DB_USER"):
        validate_environment(values)


def test_requires_explicit_disposable_database_opt_in():
    values = valid_test_environment()
    values.pop(OPT_IN_VARIABLE)

    with pytest.raises(SafetyCheckError, match=OPT_IN_VARIABLE):
        validate_environment(values)


def test_requires_all_database_fields_and_valid_port():
    values = valid_test_environment()
    values.pop("DB_PASSWORD")
    with pytest.raises(SafetyCheckError, match="DB_PASSWORD"):
        validate_environment(values)

    values = valid_test_environment()
    values["DB_PORT"] = "70000"
    with pytest.raises(SafetyCheckError, match="DB_PORT"):
        validate_environment(values)


def test_command_refuses_to_connect_without_execute_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["verify_postgres_migration.py"])

    with pytest.raises(SystemExit) as error:
        migration_verifier.main()

    assert error.value.code == 2
