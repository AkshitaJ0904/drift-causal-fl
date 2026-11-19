"""Tests for coordination.http_coordinator — Sprint 4.

Uses httpx MockTransport to test the HTTP coordinator adapter without a real
server. Covers:
- URL validation / SSRF guard
- Successful selection (true/false)
- Successful sample_count
- 404 responses → None
- Non-200/non-404 → None with warning
- Network / timeout errors → None
- Protocol does not satisfy CoordinatorAdapter at runtime
- CoordinatorBackedSampleCountProvider integration with HttpCoordinatorAdapter
"""
from __future__ import annotations

import logging

import httpx
import pytest

from coordination.coordinator_adapter import CoordinatorBackedSampleCountProvider
from coordination.http_coordinator import (
    CoordinatorConfigError,
    HttpCoordinatorAdapter,
    _validate_coordinator_url,
)

# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

class TestValidateCoordinatorUrl:
    def test_valid_https(self):
        _validate_coordinator_url("https://coordinator.example.com")

    def test_loopback_http_allowed(self):
        _validate_coordinator_url("http://localhost/api")
        _validate_coordinator_url("http://127.0.0.1/api")
        _validate_coordinator_url("http://[::1]/api")

    def test_non_loopback_http_rejected(self):
        with pytest.raises(CoordinatorConfigError, match="HTTPS"):
            _validate_coordinator_url("http://coordinator.example.com/api")

    def test_empty_url_rejected(self):
        with pytest.raises(CoordinatorConfigError):
            _validate_coordinator_url("")

    def test_no_host_rejected(self):
        with pytest.raises(CoordinatorConfigError):
            _validate_coordinator_url("https:///path")


# ---------------------------------------------------------------------------
# MockTransport helper
# ---------------------------------------------------------------------------

def _make_transport(responses: dict) -> httpx.MockTransport:
    """Build a MockTransport from a dict of path → (status_code, body_dict)."""
    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for key, (status, body) in responses.items():
            if key in path:
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(_handler)


def _make_adapter(responses: dict, **kwargs) -> HttpCoordinatorAdapter:
    adapter = HttpCoordinatorAdapter(
        base_url="https://coordinator.example.com",
        token="test-token",
        **kwargs,
    )
    adapter._client = httpx.Client(
        transport=_make_transport(responses),
        follow_redirects=False,
    )
    return adapter


# ---------------------------------------------------------------------------
# is_client_selected
# ---------------------------------------------------------------------------

class TestIsClientSelected:
    def test_selected_true(self):
        adapter = _make_adapter({"/selection": (200, {"selected": True})})
        assert adapter.is_client_selected(client_id="c1", round_number=1) is True

    def test_selected_false(self):
        adapter = _make_adapter({"/selection": (200, {"selected": False})})
        assert adapter.is_client_selected(client_id="c1", round_number=1) is False

    def test_404_returns_none(self):
        adapter = _make_adapter({})
        assert adapter.is_client_selected(client_id="unknown", round_number=1) is None

    def test_non_200_returns_none(self, caplog):
        adapter = _make_adapter({"/selection": (500, {"detail": "internal error"})})
        with caplog.at_level(logging.WARNING, logger="coordination.http_coordinator"):
            result = adapter.is_client_selected(client_id="c1", round_number=1)
        assert result is None
        assert any("HTTP 500" in m for m in [r.message for r in caplog.records])

    def test_malformed_json_response_returns_none(self, caplog):
        def _handler(request):
            return httpx.Response(200, json={"wrong_key": "not_a_bool"})

        adapter = HttpCoordinatorAdapter(
            base_url="https://coordinator.example.com",
            token="tok",
        )
        adapter._client = httpx.Client(
            transport=httpx.MockTransport(_handler),
            follow_redirects=False,
        )
        with caplog.at_level(logging.WARNING):
            result = adapter.is_client_selected(client_id="c1", round_number=1)
        assert result is None

    def test_network_error_returns_none(self, caplog):
        def _handler(request):
            raise httpx.ConnectError("refused")

        adapter = HttpCoordinatorAdapter(
            base_url="https://coordinator.example.com",
            token="tok",
        )
        adapter._client = httpx.Client(
            transport=httpx.MockTransport(_handler),
            follow_redirects=False,
        )
        with caplog.at_level(logging.WARNING):
            result = adapter.is_client_selected(client_id="c1", round_number=1)
        assert result is None

    def test_timeout_returns_none(self, caplog):
        def _handler(request):
            raise httpx.TimeoutException("timed out")

        adapter = HttpCoordinatorAdapter(
            base_url="https://coordinator.example.com",
            token="tok",
        )
        adapter._client = httpx.Client(
            transport=httpx.MockTransport(_handler),
            follow_redirects=False,
        )
        with caplog.at_level(logging.WARNING):
            result = adapter.is_client_selected(client_id="c1", round_number=1)
        assert result is None


# ---------------------------------------------------------------------------
# get_expected_sample_count
# ---------------------------------------------------------------------------

class TestGetExpectedSampleCount:
    def test_returns_count(self):
        adapter = _make_adapter({"/sample_count": (200, {"expected_count": 500})})
        result = adapter.get_expected_sample_count(
            client_id="c1", update_id="u1", round_number=1
        )
        assert result == 500

    def test_404_returns_none(self):
        adapter = _make_adapter({})
        result = adapter.get_expected_sample_count(
            client_id="unknown", update_id="u1", round_number=1
        )
        assert result is None

    def test_non_200_returns_none(self):
        adapter = _make_adapter({"/sample_count": (503, {"detail": "unavailable"})})
        result = adapter.get_expected_sample_count(
            client_id="c1", update_id="u1", round_number=1
        )
        assert result is None

    def test_zero_count_returns_none(self, caplog):
        adapter = _make_adapter({"/sample_count": (200, {"expected_count": 0})})
        with caplog.at_level(logging.WARNING):
            result = adapter.get_expected_sample_count(
                client_id="c1", update_id="u1", round_number=1
            )
        assert result is None

    def test_negative_count_returns_none(self, caplog):
        adapter = _make_adapter({"/sample_count": (200, {"expected_count": -5})})
        with caplog.at_level(logging.WARNING):
            result = adapter.get_expected_sample_count(
                client_id="c1", update_id="u1", round_number=1
            )
        assert result is None

    def test_missing_field_returns_none(self, caplog):
        adapter = _make_adapter({"/sample_count": (200, {"other": 100})})
        with caplog.at_level(logging.WARNING):
            result = adapter.get_expected_sample_count(
                client_id="c1", update_id="u1", round_number=1
            )
        assert result is None

    def test_network_error_returns_none(self, caplog):
        def _handler(request):
            raise httpx.ConnectError("refused")

        adapter = HttpCoordinatorAdapter(
            base_url="https://coordinator.example.com",
            token="tok",
        )
        adapter._client = httpx.Client(
            transport=httpx.MockTransport(_handler),
            follow_redirects=False,
        )
        with caplog.at_level(logging.WARNING):
            result = adapter.get_expected_sample_count(
                client_id="c1", update_id="u1", round_number=1
            )
        assert result is None


# ---------------------------------------------------------------------------
# CoordinatorBackedSampleCountProvider integration
# ---------------------------------------------------------------------------

class TestCoordinatorBackedProvider:
    def test_selected_with_count(self):
        def _handler(request):
            if "/selection" in request.url.path:
                return httpx.Response(200, json={"selected": True})
            if "/sample_count" in request.url.path:
                return httpx.Response(200, json={"expected_count": 300})
            return httpx.Response(404, json={})

        adapter = HttpCoordinatorAdapter(
            base_url="https://coordinator.example.com",
            token="tok",
        )
        adapter._client = httpx.Client(
            transport=httpx.MockTransport(_handler),
            follow_redirects=False,
        )
        provider = CoordinatorBackedSampleCountProvider(adapter)
        result = provider.get_verified_count(
            client_id="c1", update_id="u1", round_number=1
        )
        assert result == 300

    def test_not_selected_returns_none(self):
        def _handler(request):
            if "/selection" in request.url.path:
                return httpx.Response(200, json={"selected": False})
            return httpx.Response(200, json={"expected_count": 999})

        adapter = HttpCoordinatorAdapter(
            base_url="https://coordinator.example.com",
            token="tok",
        )
        adapter._client = httpx.Client(
            transport=httpx.MockTransport(_handler),
            follow_redirects=False,
        )
        provider = CoordinatorBackedSampleCountProvider(adapter)
        result = provider.get_verified_count(
            client_id="c1", update_id="u1", round_number=1
        )
        assert result is None

    def test_coordinator_unreachable_returns_none(self):
        def _handler(request):
            raise httpx.ConnectError("refused")

        adapter = HttpCoordinatorAdapter(
            base_url="https://coordinator.example.com",
            token="tok",
        )
        adapter._client = httpx.Client(
            transport=httpx.MockTransport(_handler),
            follow_redirects=False,
        )
        provider = CoordinatorBackedSampleCountProvider(adapter)
        result = provider.get_verified_count(
            client_id="c1", update_id="u1", round_number=1
        )
        assert result is None

    def test_provider_name_includes_adapter_name(self):
        adapter = HttpCoordinatorAdapter(
            base_url="https://coordinator.example.com",
            token="tok",
            name="prod-coordinator",
        )
        provider = CoordinatorBackedSampleCountProvider(adapter)
        assert "prod-coordinator" in provider.name


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

def test_http_coordinator_satisfies_protocol():
    from coordination.coordinator_adapter import CoordinatorAdapter

    adapter = HttpCoordinatorAdapter(
        base_url="https://coordinator.example.com",
        token="tok",
    )
    assert isinstance(adapter, CoordinatorAdapter)


def test_no_token_on_non_loopback_emits_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="coordination.http_coordinator"):
        HttpCoordinatorAdapter(base_url="https://coordinator.example.com")
    assert any("unauthenticated" in r.message for r in caplog.records)


def test_token_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="coordination.http_coordinator"):
        HttpCoordinatorAdapter(
            base_url="https://coordinator.example.com", token="secret"
        )
    assert not any("unauthenticated" in r.message for r in caplog.records)
