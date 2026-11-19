"""Structural evidence tests for requirements that have no other dedicated test.

Covers:
  S1-10 — canonical httpx (not httpx2) used as HTTP client
  S3-07 — startup security checklist document exists
  S4-05 — threading.Lock present on HttpCoordinatorAdapter
  S4-07 — bounded httpx.Timeout configured on HttpCoordinatorAdapter
  S5-09 — detection dataset inventory document exists
"""
from __future__ import annotations

import threading
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_LOCK = PROJECT_ROOT / "requirements.lock"


# ---------------------------------------------------------------------------
# S1-10 — canonical httpx, httpx2 absent
# ---------------------------------------------------------------------------

class TestS1_10_CanonicalHttpx:
    def test_httpx_present_in_requirements_lock(self):
        """requirements.lock must contain an httpx entry."""
        lines = REQUIREMENTS_LOCK.read_text(encoding="utf-8").splitlines()
        httpx_lines = [ln for ln in lines if ln.startswith("httpx==")]
        assert len(httpx_lines) == 1, (
            "Expected exactly one httpx== entry in requirements.lock"
        )

    def test_httpx2_absent_from_requirements_lock(self):
        """httpx2 must not appear in requirements.lock (replaced by httpx)."""
        content = REQUIREMENTS_LOCK.read_text(encoding="utf-8")
        assert "httpx2" not in content, (
            "httpx2 found in requirements.lock — it must not be present"
        )

    def test_http_coordinator_imports_httpx_not_httpx2(self):
        """http_coordinator must import httpx, and httpx2 must not be importable."""
        import coordination.http_coordinator as mod

        assert mod.httpx is httpx, (
            "coordination.http_coordinator must use canonical httpx"
        )
        with pytest.raises(ModuleNotFoundError):
            import httpx2  # type: ignore[import]  # noqa: F401


# ---------------------------------------------------------------------------
# S3-07 — startup security checklist document
# ---------------------------------------------------------------------------

class TestS3_07_StartupChecklist:
    def test_windows_startup_md_exists(self):
        """configs/windows_startup.md must exist and be non-empty."""
        path = PROJECT_ROOT / "configs" / "windows_startup.md"
        assert path.exists(), "configs/windows_startup.md not found"
        assert path.stat().st_size > 0, "configs/windows_startup.md is empty"

    def test_windows_startup_md_covers_required_sections(self):
        """configs/windows_startup.md must cover all 7 checklist items."""
        path = PROJECT_ROOT / "configs" / "windows_startup.md"
        content = path.read_text(encoding="utf-8").lower()
        required_keywords = [
            "operator",
            "token",
            "environment",
            "ssl",
            "firewall",
            "log",
            "migration",
        ]
        missing = [kw for kw in required_keywords if kw not in content]
        assert not missing, (
            f"windows_startup.md missing coverage for: {missing}"
        )


# ---------------------------------------------------------------------------
# S4-05 — threading.Lock on HttpCoordinatorAdapter
# ---------------------------------------------------------------------------

class TestS4_05_ThreadSafety:
    def test_adapter_has_lock_attribute(self):
        """HttpCoordinatorAdapter must hold a threading.Lock for thread safety."""
        from coordination.http_coordinator import HttpCoordinatorAdapter

        adapter = HttpCoordinatorAdapter(
            base_url="https://coordinator.example.com",
            token="test-tok",
        )
        assert hasattr(adapter, "_lock"), (
            "HttpCoordinatorAdapter must have a _lock attribute"
        )
        assert isinstance(adapter._lock, type(threading.Lock())), (
            "HttpCoordinatorAdapter._lock must be a threading.Lock"
        )

    def test_lock_is_acquired_during_coordinator_call(self):
        """Lock context manager must be entered for each coordinator HTTP call."""
        from unittest.mock import MagicMock

        from coordination.http_coordinator import HttpCoordinatorAdapter

        adapter = HttpCoordinatorAdapter(
            base_url="https://coordinator.example.com",
            token="test-tok",
        )
        adapter._client = httpx.Client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, json={"selected": True})
            ),
            follow_redirects=False,
        )
        mock_lock = MagicMock()
        mock_lock.__enter__ = MagicMock(return_value=None)
        mock_lock.__exit__ = MagicMock(return_value=False)
        adapter._lock = mock_lock

        adapter.is_client_selected(client_id="c1", round_number=1)

        mock_lock.__enter__.assert_called_once()


# ---------------------------------------------------------------------------
# S4-07 — bounded httpx.Timeout
# ---------------------------------------------------------------------------

class TestS4_07_BoundedTimeout:
    def test_default_timeout_configured(self):
        """_DEFAULT_TIMEOUT must be an httpx.Timeout instance."""
        from coordination.http_coordinator import _DEFAULT_TIMEOUT

        assert isinstance(_DEFAULT_TIMEOUT, httpx.Timeout), (
            "_DEFAULT_TIMEOUT must be httpx.Timeout"
        )

    def test_default_timeout_connect_bound(self):
        """connect timeout must be <= 10 seconds (documented as 5.0 s)."""
        from coordination.http_coordinator import _DEFAULT_TIMEOUT

        assert _DEFAULT_TIMEOUT.connect is not None
        assert _DEFAULT_TIMEOUT.connect == pytest.approx(5.0), (
            "connect timeout must be 5.0 s"
        )

    def test_default_timeout_read_bound(self):
        """read timeout must be <= 30 seconds (documented as 10.0 s)."""
        from coordination.http_coordinator import _DEFAULT_TIMEOUT

        assert _DEFAULT_TIMEOUT.read is not None
        assert _DEFAULT_TIMEOUT.read == pytest.approx(10.0), (
            "read timeout must be 10.0 s"
        )

    def test_default_timeout_write_bound(self):
        """write timeout must be bounded (documented as 10.0 s)."""
        from coordination.http_coordinator import _DEFAULT_TIMEOUT

        assert _DEFAULT_TIMEOUT.write is not None
        assert _DEFAULT_TIMEOUT.write == pytest.approx(10.0), (
            "write timeout must be 10.0 s"
        )

    def test_default_timeout_pool_bound(self):
        """pool timeout must be bounded (documented as 5.0 s)."""
        from coordination.http_coordinator import _DEFAULT_TIMEOUT

        assert _DEFAULT_TIMEOUT.pool is not None
        assert _DEFAULT_TIMEOUT.pool == pytest.approx(5.0), (
            "pool timeout must be 5.0 s"
        )

    def test_adapter_uses_bounded_timeout(self):
        """HttpCoordinatorAdapter must pass the default timeout to its client."""
        from coordination.http_coordinator import _DEFAULT_TIMEOUT, HttpCoordinatorAdapter

        adapter = HttpCoordinatorAdapter(
            base_url="https://coordinator.example.com",
            token="test-tok",
        )
        assert adapter._client.timeout == _DEFAULT_TIMEOUT, (
            "HttpCoordinatorAdapter client timeout must equal _DEFAULT_TIMEOUT"
        )


# ---------------------------------------------------------------------------
# S5-09 — detection dataset inventory document
# ---------------------------------------------------------------------------

class TestS5_09_DatasetInventory:
    def test_detection_dataset_inventory_exists(self):
        """configs/detection_dataset_inventory.md must exist and be non-empty."""
        path = PROJECT_ROOT / "configs" / "detection_dataset_inventory.md"
        assert path.exists(), "configs/detection_dataset_inventory.md not found"
        assert path.stat().st_size > 0, "configs/detection_dataset_inventory.md is empty"

    def test_detection_dataset_inventory_covers_required_sections(self):
        """configs/detection_dataset_inventory.md must cover the 5 required sections."""
        path = PROJECT_ROOT / "configs" / "detection_dataset_inventory.md"
        content = path.read_text(encoding="utf-8").lower()
        required_keywords = [
            "dataset",
            "source",
            "feature",
            "threshold",
            "version",
        ]
        missing = [kw for kw in required_keywords if kw not in content]
        assert not missing, (
            f"detection_dataset_inventory.md missing coverage for: {missing}"
        )
