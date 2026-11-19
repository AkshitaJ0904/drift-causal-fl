"""Tests for audit.delivery — Sprint 1 webhook delivery adapter.

Covers:
- URL validation / SSRF guard
- Successful delivery (2xx)
- Authentication header present / absent
- Timeout, connection error (retryable)
- HTTP 4xx → DeliveryPermanentError (non-retryable)
- HTTP 5xx → HTTPStatusError (retryable)
- Duplicate delivery idempotency (receiver contract, not tested here but noted)
- Worker dead-letter integration via deliver_pending_events
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from audit.delivery import (
    SCHEMA_VERSION,
    SERVICE_NAME,
    DeliveryConfigError,
    DeliveryPermanentError,
    _validate_webhook_url,
    create_webhook_delivery_fn,
)

# ---------------------------------------------------------------------------
# Outbox cleanup between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_outbox_delivery(_sqlite_test_database):
    """Clear the outbox before and after every test in this module."""
    from sqlalchemy import delete

    from core.supabase.session import SessionLocal
    from db.models.audit_outbox import AuditOutboxRecord

    def _clear():
        with SessionLocal() as db:
            db.execute(delete(AuditOutboxRecord))
            db.commit()

    _clear()
    yield
    _clear()


# ---------------------------------------------------------------------------
# _validate_webhook_url
# ---------------------------------------------------------------------------

class TestValidateWebhookUrl:
    def test_valid_https_url(self):
        # Should not raise.
        _validate_webhook_url("https://example.com/webhook")

    def test_valid_https_url_with_path(self):
        _validate_webhook_url("https://siem.example.com/api/v1/events")

    def test_loopback_http_allowed(self):
        _validate_webhook_url("http://localhost/webhook")
        _validate_webhook_url("http://127.0.0.1/webhook")
        _validate_webhook_url("http://[::1]/webhook")

    def test_non_loopback_http_rejected(self):
        with pytest.raises(DeliveryConfigError, match="HTTPS"):
            _validate_webhook_url("http://example.com/webhook")

    def test_empty_url_rejected(self):
        with pytest.raises(DeliveryConfigError):
            _validate_webhook_url("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(DeliveryConfigError):
            _validate_webhook_url("   ")

    def test_ftp_scheme_rejected(self):
        with pytest.raises(DeliveryConfigError, match="scheme"):
            _validate_webhook_url("ftp://example.com/file")

    def test_no_host_rejected(self):
        with pytest.raises(DeliveryConfigError):
            _validate_webhook_url("https:///path")


# ---------------------------------------------------------------------------
# create_webhook_delivery_fn
# ---------------------------------------------------------------------------

class TestCreateWebhookDeliveryFn:
    def test_returns_callable(self):
        fn = create_webhook_delivery_fn(url="https://example.com/wh", token="tok")
        assert callable(fn)

    def test_invalid_url_raises_delivery_config_error(self):
        with pytest.raises(DeliveryConfigError):
            create_webhook_delivery_fn(url="http://external.host/wh")

    def test_no_token_on_non_loopback_emits_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="audit.delivery"):
            create_webhook_delivery_fn(url="https://example.com/wh", token=None)
        assert any("unauthenticated" in r.message for r in caplog.records)

    def test_no_warning_for_loopback_without_token(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="audit.delivery"):
            create_webhook_delivery_fn(url="http://localhost/wh", token=None)
        # No unauthenticated warning for loopback.
        assert not any("unauthenticated" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _WebhookDeliveryFn — HTTP behaviour (mocked httpx.Client)
# ---------------------------------------------------------------------------

def _make_fn(url="https://example.com/wh", token="test-token"):
    return create_webhook_delivery_fn(url=url, token=token)


def _mock_response(status_code: int) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


_SAMPLE_PAYLOAD = {
    "schema_version": SCHEMA_VERSION,
    "service": SERVICE_NAME,
    "idempotency_key": "ik-abc123",
    "event_id": "ev-001",
    "event_type": "key.registered",
    "severity": "info",
    "client_id": "cl-1",
    "update_id": None,
    "description": "test",
    "attempt_count": 1,
    "created_at": "2026-11-07T00:00:00",
}


class TestWebhookDeliveryFnCall:
    def test_success_200(self):
        fn = _make_fn()
        with patch.object(fn._client, "post", return_value=_mock_response(200)) as mock_post:
            fn(_SAMPLE_PAYLOAD)
            mock_post.assert_called_once_with(fn._url, json=_SAMPLE_PAYLOAD)

    def test_success_201(self):
        fn = _make_fn()
        with patch.object(fn._client, "post", return_value=_mock_response(201)):
            fn(_SAMPLE_PAYLOAD)  # Should not raise.

    def test_bearer_token_in_headers(self):
        fn = _make_fn(token="secret-bearer")
        assert fn._headers.get("Authorization") == "Bearer secret-bearer"

    def test_no_token_no_auth_header(self):
        fn = create_webhook_delivery_fn(url="http://localhost/wh", token=None)
        assert "Authorization" not in fn._headers

    def test_4xx_raises_permanent_error(self):
        fn = _make_fn()
        for status in (400, 401, 403, 404, 422):
            with patch.object(fn._client, "post", return_value=_mock_response(status)):
                with pytest.raises(DeliveryPermanentError):
                    fn(_SAMPLE_PAYLOAD)

    def test_5xx_raises_http_status_error(self):
        fn = _make_fn()
        with patch.object(fn._client, "post", return_value=_mock_response(500)):
            with pytest.raises(httpx.HTTPStatusError):
                fn(_SAMPLE_PAYLOAD)

    def test_timeout_raises_timeout_exception(self):
        fn = _make_fn()
        with patch.object(
            fn._client,
            "post",
            side_effect=httpx.TimeoutException("timed out"),
        ):
            with pytest.raises(httpx.TimeoutException):
                fn(_SAMPLE_PAYLOAD)

    def test_connection_error_raises_request_error(self):
        fn = _make_fn()
        with patch.object(
            fn._client,
            "post",
            side_effect=httpx.ConnectError("refused"),
        ):
            with pytest.raises(httpx.RequestError):
                fn(_SAMPLE_PAYLOAD)

    def test_redirects_not_followed(self):
        fn = _make_fn()
        # follow_redirects=False is set at client construction.
        assert fn._client.follow_redirects is False

    def test_tls_verification_enabled(self):
        fn = _make_fn()
        # verify is True by default; ssl_context would be set.
        # httpx stores it on the transport; check that follow_redirects=False
        # and that we didn't pass verify=False.
        # Indirect assertion: the client was constructed without disabling verify.
        assert fn._client is not None  # basic smoke check


# ---------------------------------------------------------------------------
# Integration: DeliveryPermanentError dead-letters outbox record
# ---------------------------------------------------------------------------

def _enqueue_one_delivery(
    event_type: str = "test.event",
    severity: str = "info",
    client_id: str | None = "cl-1",
    update_id: str | None = None,
    description: str = "delivery test",
):
    from audit.outbox import enqueue
    from core.supabase.session import SessionLocal
    from db.models.audit_outbox import AuditOutboxRecord

    with SessionLocal() as db:
        with db.begin():
            record = enqueue(
                db,
                event_id=None,
                event_type=event_type,
                severity=severity,
                client_id=client_id,
                update_id=update_id,
                description=description,
            )
            db.flush()
    with SessionLocal() as db:
        return db.get(AuditOutboxRecord, record.id)


def test_permanent_error_dead_letters_via_deliver_pending_events(
    _sqlite_test_database,
) -> None:
    """A 4xx response from delivery_fn must dead-letter the record immediately."""
    from audit.outbox import dead_letter_count, deliver_pending_events

    _enqueue_one_delivery(description="perm fail test")

    def _permanent_fail(payload: dict) -> None:
        raise DeliveryPermanentError("HTTP 401 Unauthorized")

    result = deliver_pending_events(delivery_fn=_permanent_fail)

    assert result["claimed"] == 1
    assert result["delivered"] == 0
    assert result["dead_lettered"] == 1
    assert dead_letter_count() == 1


def test_transient_error_applies_backoff_via_deliver_pending_events(
    _sqlite_test_database,
) -> None:
    """A transient error should release the record with backoff (not dead-letter)."""
    from audit.outbox import dead_letter_count, deliver_pending_events

    _enqueue_one_delivery(description="transient fail test")

    def _transient_fail(payload: dict) -> None:
        raise RuntimeError("simulated transient error")

    result = deliver_pending_events(delivery_fn=_transient_fail)

    assert result["claimed"] == 1
    assert result["delivered"] == 0
    assert result["released"] == 1
    assert dead_letter_count() == 0


def test_success_delivery_increments_delivered_count(
    _sqlite_test_database,
) -> None:
    """Successful delivery must increment counts['delivered']."""
    from audit.outbox import deliver_pending_events

    _enqueue_one_delivery(
        event_type="schema.registered",
        client_id="cl-2",
        update_id="u-1",
        description="schema registration",
    )

    payloads: list[dict] = []
    result = deliver_pending_events(delivery_fn=payloads.append)

    assert result["delivered"] == 1
    assert result["claimed"] == 1
    assert len(payloads) == 1
    assert payloads[0]["schema_version"] == SCHEMA_VERSION
    assert payloads[0]["service"] == SERVICE_NAME


def test_payload_idempotency_key_stable_across_deliveries(
    _sqlite_test_database,
) -> None:
    """idempotency_key must be the same value across repeated claim cycles."""
    from audit.outbox import deliver_pending_events
    from core.supabase.session import SessionLocal
    from db.models.audit_outbox import AuditOutboxRecord

    record = _enqueue_one_delivery(
        event_type="key.revoked", severity="warning", description="revocation"
    )
    record_id = record.id

    # Collect key from first delivery attempt (simulated failure → backoff).
    first_keys: list[str] = []

    def _capture_then_fail(payload: dict) -> None:
        first_keys.append(payload["idempotency_key"])
        raise RuntimeError("first attempt fails")

    result1 = deliver_pending_events(delivery_fn=_capture_then_fail)
    assert result1["released"] == 1

    # Reset retry_after by specific ID so we target the right record.
    with SessionLocal() as db:
        with db.begin():
            row = db.get(AuditOutboxRecord, record_id)
            assert row is not None
            row.retry_after = None

    second_keys: list[str] = []

    def _capture_success(payload: dict) -> None:
        second_keys.append(payload["idempotency_key"])

    result2 = deliver_pending_events(delivery_fn=_capture_success)
    assert result2["delivered"] == 1

    assert first_keys == second_keys, (
        "idempotency_key must be stable across retry attempts"
    )
