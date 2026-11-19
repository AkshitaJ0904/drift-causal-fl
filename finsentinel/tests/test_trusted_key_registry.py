"""Tests for the durable DB-backed trusted-key registry (core/key_registry.py)."""


import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from core.key_registry import (
    RegistryUnavailableError,
    TrustedKey,
    clear_trusted_keys,
    get_trusted_key,
    register_trusted_key,
    revoke_trusted_key,
)
from core.supabase.session import SessionLocal
from db.models.trusted_key import TrustedKeyRecord

# ---------------------------------------------------------------------------
# Shared test keys
# ---------------------------------------------------------------------------

_PRIV_A = Ed25519PrivateKey.generate()
_PUB_A = _PRIV_A.public_key()

_PRIV_B = Ed25519PrivateKey.generate()
_PUB_B = _PRIV_B.public_key()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_trusted_keys()
    yield
    clear_trusted_keys()


# ---------------------------------------------------------------------------
# Registration and retrieval
# ---------------------------------------------------------------------------


def test_register_and_retrieve_active_key() -> None:
    register_trusted_key("key-001", "client-A", _PUB_A, max_sample_count=100)
    result = get_trusted_key("key-001")

    assert result is not None
    assert isinstance(result, TrustedKey)
    assert result.key_id == "key-001"
    assert result.client_id == "client-A"
    assert result.max_sample_count == 100


def test_register_without_max_sample_count() -> None:
    register_trusted_key("key-002", "client-B", _PUB_B)
    result = get_trusted_key("key-002")

    assert result is not None
    assert result.max_sample_count is None


def test_retrieved_public_key_verifies_signature() -> None:
    """The PEM round-trip must preserve the cryptographic public key."""
    register_trusted_key("key-003", "client-A", _PUB_A)
    result = get_trusted_key("key-003")

    assert result is not None
    msg = b"test-message"
    sig = _PRIV_A.sign(msg)
    result.public_key.verify(sig, msg)  # raises if key mismatch


def test_get_unknown_key_returns_none() -> None:
    assert get_trusted_key("nonexistent-key") is None


def test_register_same_key_id_updates_record() -> None:
    register_trusted_key("key-004", "client-A", _PUB_A)
    register_trusted_key("key-004", "client-B", _PUB_B, max_sample_count=50)

    result = get_trusted_key("key-004")
    assert result is not None
    assert result.client_id == "client-B"
    assert result.max_sample_count == 50


# ---------------------------------------------------------------------------
# Validation on register
# ---------------------------------------------------------------------------


def test_register_empty_key_id_raises() -> None:
    with pytest.raises(ValueError, match="key_id"):
        register_trusted_key("", "client-A", _PUB_A)


def test_register_empty_client_id_raises() -> None:
    with pytest.raises(ValueError, match="client_id"):
        register_trusted_key("key-005", "", _PUB_A)


def test_register_zero_max_sample_count_raises() -> None:
    with pytest.raises(ValueError, match="max_sample_count"):
        register_trusted_key("key-006", "client-A", _PUB_A, max_sample_count=0)


def test_register_negative_max_sample_count_raises() -> None:
    with pytest.raises(ValueError, match="max_sample_count"):
        register_trusted_key("key-007", "client-A", _PUB_A, max_sample_count=-1)


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------


def test_revoke_active_key_returns_true() -> None:
    register_trusted_key("key-010", "client-A", _PUB_A)
    assert revoke_trusted_key("key-010") is True


def test_revoked_key_not_returned_by_get() -> None:
    register_trusted_key("key-011", "client-A", _PUB_A)
    revoke_trusted_key("key-011")

    assert get_trusted_key("key-011") is None


def test_revoke_nonexistent_key_returns_false() -> None:
    assert revoke_trusted_key("no-such-key") is False


def test_revoke_already_revoked_returns_false() -> None:
    register_trusted_key("key-012", "client-A", _PUB_A)
    revoke_trusted_key("key-012")
    assert revoke_trusted_key("key-012") is False


def test_register_revoked_key_id_raises() -> None:
    register_trusted_key("key-013", "client-A", _PUB_A)
    revoke_trusted_key("key-013")

    with pytest.raises(ValueError, match="revoked"):
        register_trusted_key("key-013", "client-A", _PUB_A)


# ---------------------------------------------------------------------------
# Key rotation
# ---------------------------------------------------------------------------


def test_key_rotation_registers_new_key_after_revocation() -> None:
    """Safe rotation: revoke old key-id, register new key-id for same client."""
    register_trusted_key("key-old", "client-A", _PUB_A)
    revoke_trusted_key("key-old")
    register_trusted_key("key-new", "client-A", _PUB_B)

    assert get_trusted_key("key-old") is None
    result = get_trusted_key("key-new")
    assert result is not None
    assert result.client_id == "client-A"


# ---------------------------------------------------------------------------
# DB failure (fail-closed)
# ---------------------------------------------------------------------------


class _FailingSession:
    def __enter__(self):
        raise SQLAlchemyError("simulated DB failure")

    def __exit__(self, *args):
        pass


def test_db_failure_on_get_raises_registry_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("core.key_registry.SessionLocal", lambda: _FailingSession())
    with pytest.raises(RegistryUnavailableError):
        get_trusted_key("any-key")


def test_db_failure_on_register_raises_registry_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("core.key_registry.SessionLocal", lambda: _FailingSession())
    with pytest.raises(RegistryUnavailableError):
        register_trusted_key("key-X", "client-A", _PUB_A)


def test_db_failure_on_revoke_raises_registry_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("core.key_registry.SessionLocal", lambda: _FailingSession())
    with pytest.raises(RegistryUnavailableError):
        revoke_trusted_key("key-X")


def test_corrupted_pem_in_db_raises_registry_unavailable() -> None:
    """get_trusted_key must raise RegistryUnavailableError, not propagate a raw
    ValueError/Exception, when the PEM stored in the DB is not valid."""
    register_trusted_key("key-corrupt", "client-A", _PUB_A)

    # Directly overwrite the PEM with garbage to simulate DB corruption.
    with SessionLocal() as db:
        db.execute(
            update(TrustedKeyRecord)
            .where(TrustedKeyRecord.key_id == "key-corrupt")
            .values(public_key_pem="NOT VALID PEM DATA")
        )
        db.commit()

    with pytest.raises(RegistryUnavailableError, match="corrupted"):
        get_trusted_key("key-corrupt")


# ---------------------------------------------------------------------------
# Clear (environment guard)
# ---------------------------------------------------------------------------


def test_clear_removes_all_keys() -> None:
    register_trusted_key("key-100", "client-A", _PUB_A)
    register_trusted_key("key-101", "client-B", _PUB_B)

    clear_trusted_keys()

    assert get_trusted_key("key-100") is None
    assert get_trusted_key("key-101") is None


def test_clear_outside_safe_environment_raises(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="production"):
        clear_trusted_keys()


# ---------------------------------------------------------------------------
# Persistence (simulated restart: re-read without re-registering)
# ---------------------------------------------------------------------------


def test_registered_key_persists_across_session_boundaries() -> None:
    """Data survives; a second lookup (new Session) finds the same record."""
    register_trusted_key("key-200", "client-A", _PUB_A, max_sample_count=42)

    # Simulate a second process / new session by calling get in a fresh call.
    result1 = get_trusted_key("key-200")
    result2 = get_trusted_key("key-200")

    assert result1 is not None
    assert result2 is not None
    assert result1.key_id == result2.key_id
    assert result1.client_id == result2.client_id
    assert result1.max_sample_count == result2.max_sample_count
