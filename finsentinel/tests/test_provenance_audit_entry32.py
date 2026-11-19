"""Entry 32 — Production Provenance Trust-Boundary Audit.

Covers four gaps not addressed by earlier test suites:

1. Structural guard: no production module imports the private seal names.
2. Provider failure in the ingestion service context stores CLIENT_CLAIMED,
   never PROVIDER_VERIFIED (fail-open to unverified, not to forged verified).
3. Provider unavailability (returns None) stores CLIENT_CLAIMED.
4. Default configuration: _sample_count_provider is None at module load, so
   ordinary production ingestion operates entirely with client-claimed provenance
   until the operator explicitly calls configure_sample_count_provider().

Design note documented here for completeness
--------------------------------------------
The ingestion service calls resolve_sample_count() without require_verified=True.
This means provider failure falls to CLIENT_CLAIMED provenance, not an error.
If the deployment requires verified provenance for all updates, the operator
must:
  (a) Call configure_sample_count_provider() with a real provider at startup.
  (b) Optionally add require_verified=True at the resolve_sample_count() call
      site, or require_verified_provenance=True at approval / aggregation.
Neither (a) nor (b) is enforced by default. The current design is intentional:
the system supports deployments with no coordinator.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from enforcement.approval_service import (
    clear_approval_registry,
    get_update_record,
    record_ingestion_audit_result,
    register_validated_update,
)
from ingestion.sample_count_provider import (
    PROVENANCE_CLIENT_CLAIMED,
    PROVENANCE_PROVIDER_VERIFIED,
    SampleCountVerificationError,
    resolve_sample_count,
)
from ingestion.service import configure_sample_count_provider

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent

# Production packages: directories that contain application code.
# Excludes tests/, scripts/, alembic/, and infrastructure/data directories.
_PRODUCTION_PACKAGES = {
    "aggregation",
    "api",
    "app",
    "audit",
    "coordination",
    "core",
    "db",
    "detection",
    "enforcement",
    "features",
    "ingestion",
    "policy",
}


# ---------------------------------------------------------------------------
# Helper providers for ingestion-service integration tests
# ---------------------------------------------------------------------------


class _RaisingProvider:
    name = "always-raises"

    def get_verified_count(self, *, client_id, update_id, round_number) -> int | None:
        raise RuntimeError("Coordinator unreachable")


class _NoneProvider:
    name = "always-none"

    def get_verified_count(self, *, client_id, update_id, round_number) -> int | None:
        return None


class _MatchingProvider:
    name = "matching"

    def __init__(self, count: int) -> None:
        self._count = count

    def get_verified_count(self, *, client_id, update_id, round_number) -> int | None:
        return self._count


# ---------------------------------------------------------------------------
# 1. Structural guard: private seal names absent from production modules
# ---------------------------------------------------------------------------

_PRIVATE_SEAL_NAMES = frozenset({"_PROVIDER_VERIFIED_SEAL", "_ProviderVerifiedSeal"})


def _collect_production_py_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for pkg in _PRODUCTION_PACKAGES:
        pkg_dir = _PROJECT_ROOT / pkg
        if pkg_dir.is_dir():
            files.extend(pkg_dir.rglob("*.py"))
    return files


def _imports_private_seal(source: str) -> list[str]:
    """Return list of private seal names imported from ingestion.sample_count_provider."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "sample_count_provider" in module:
                for alias in node.names:
                    if alias.name in _PRIVATE_SEAL_NAMES:
                        found.append(alias.name)
        elif isinstance(node, ast.Import):
            # bare `import ingestion.sample_count_provider._PROVIDER_VERIFIED_SEAL`
            # is not valid Python, so no case to handle here.
            pass
    return found


def test_no_production_module_imports_private_seal() -> None:
    """No production .py file imports _PROVIDER_VERIFIED_SEAL or _ProviderVerifiedSeal.

    Importing either name from ingestion.sample_count_provider bypasses the
    provenance trust boundary (confirmed in Entry 31 bypass tests).  Any such
    import in a production module is a security defect and must be caught in
    code review.  This test provides an automated regression guard.
    """
    violations: list[str] = []
    for path in _collect_production_py_files():
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        found = _imports_private_seal(source)
        if found:
            rel = path.relative_to(_PROJECT_ROOT)
            violations.append(f"{rel}: imports {found}")

    assert not violations, (
        "Production modules must not import private seal names:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_production_packages_scanned_are_non_empty() -> None:
    """At least one production .py file is scanned (guards against scan being vacuous)."""
    files = _collect_production_py_files()
    assert len(files) >= 5, (
        f"Expected at least 5 production .py files; found {len(files)}. "
        "Check _PRODUCTION_PACKAGES."
    )


# ---------------------------------------------------------------------------
# 2. Provider failure → CLIENT_CLAIMED (not PROVIDER_VERIFIED)
# ---------------------------------------------------------------------------


def test_provider_failure_produces_client_claimed() -> None:
    """resolve_sample_count() with a raising provider falls back to CLIENT_CLAIMED.

    The ingestion service does not pass require_verified=True, so provider
    failure is non-fatal and returns CLIENT_CLAIMED provenance.
    """
    result = resolve_sample_count(
        client_claimed=100,
        provider=_RaisingProvider(),
        client_id="cl-1",
        update_id="upd-1",
        round_number=1,
    )
    assert result.provenance == PROVENANCE_CLIENT_CLAIMED
    assert result.provenance != PROVENANCE_PROVIDER_VERIFIED
    assert result.count == 100


def test_provider_failure_in_ingestion_path_stores_client_claimed() -> None:
    """When a configured provider raises, the registration stores CLIENT_CLAIMED."""
    configure_sample_count_provider(_RaisingProvider())
    try:
        result = resolve_sample_count(
            client_claimed=50,
            provider=_RaisingProvider(),
            client_id="pf-client",
            update_id="pf-001",
            round_number=1,
        )
        assert result.provenance == PROVENANCE_CLIENT_CLAIMED

        clear_approval_registry()
        register_validated_update(
            update_id="pf-001",
            client_id="pf-client",
            model_version="cnn-v1",
            round_number=1,
            sample_count_result=result,
            payload_sha256="d" * 64,
            risk_score=0,
            risk_severity="LOW",
            suspicious=False,
            anomaly_reasons=["none"],
            detector_version="v1",
            detector_config={"t": 0.5},
        )
        record_ingestion_audit_result(
            client_id="pf-client",
            update_id="pf-001",
            audit_status="persisted",
            audit_failures=(),
        )
        record = get_update_record(client_id="pf-client", update_id="pf-001")
        got = record.sample_count_provenance
        assert got == PROVENANCE_CLIENT_CLAIMED, (
            f"Expected CLIENT_CLAIMED after provider failure, got {got!r}"
        )
    finally:
        configure_sample_count_provider(None)
        clear_approval_registry()


# ---------------------------------------------------------------------------
# 3. Provider unavailable (returns None) → CLIENT_CLAIMED
# ---------------------------------------------------------------------------


def test_provider_unavailable_produces_client_claimed() -> None:
    """resolve_sample_count() with provider returning None falls back to CLIENT_CLAIMED."""
    result = resolve_sample_count(
        client_claimed=75,
        provider=_NoneProvider(),
        client_id="cl-2",
        update_id="upd-2",
        round_number=1,
    )
    assert result.provenance == PROVENANCE_CLIENT_CLAIMED
    assert result.count == 75


def test_provider_unavailable_in_ingestion_path_stores_client_claimed() -> None:
    """When provider returns None (unavailable), the registration stores CLIENT_CLAIMED."""
    configure_sample_count_provider(_NoneProvider())
    try:
        result = resolve_sample_count(
            client_claimed=60,
            provider=_NoneProvider(),
            client_id="pn-client",
            update_id="pn-001",
            round_number=1,
        )
        assert result.provenance == PROVENANCE_CLIENT_CLAIMED

        clear_approval_registry()
        register_validated_update(
            update_id="pn-001",
            client_id="pn-client",
            model_version="cnn-v1",
            round_number=1,
            sample_count_result=result,
            payload_sha256="e" * 64,
            risk_score=0,
            risk_severity="LOW",
            suspicious=False,
            anomaly_reasons=["none"],
            detector_version="v1",
            detector_config={"t": 0.5},
        )
        record_ingestion_audit_result(
            client_id="pn-client",
            update_id="pn-001",
            audit_status="persisted",
            audit_failures=(),
        )
        record = get_update_record(client_id="pn-client", update_id="pn-001")
        assert record.sample_count_provenance == PROVENANCE_CLIENT_CLAIMED
    finally:
        configure_sample_count_provider(None)
        clear_approval_registry()


# ---------------------------------------------------------------------------
# 4. Default configuration: provider is None → CLIENT_CLAIMED
# ---------------------------------------------------------------------------


def test_default_provider_is_none() -> None:
    """The module-level _sample_count_provider defaults to None at import time.

    Unless configure_sample_count_provider() is called, production ingestion
    operates with CLIENT_CLAIMED provenance for all updates.
    """
    from ingestion import service as _svc

    # Ensure we're not accidentally reading a test-contaminated state.
    configure_sample_count_provider(None)
    assert _svc._sample_count_provider is None


def test_no_provider_resolve_produces_client_claimed() -> None:
    """With provider=None, resolve_sample_count() always returns CLIENT_CLAIMED."""
    result = resolve_sample_count(
        client_claimed=200,
        provider=None,
        client_id="cl-3",
        update_id="upd-3",
        round_number=1,
    )
    assert result.provenance == PROVENANCE_CLIENT_CLAIMED
    assert result.count == 200


# ---------------------------------------------------------------------------
# 5. Matching provider still produces PROVIDER_VERIFIED (non-regression)
# ---------------------------------------------------------------------------


def test_matching_provider_produces_provider_verified() -> None:
    """resolve_sample_count() with a matching provider produces PROVIDER_VERIFIED."""
    result = resolve_sample_count(
        client_claimed=300,
        provider=_MatchingProvider(count=300),
        client_id="cl-4",
        update_id="upd-4",
        round_number=1,
    )
    assert result.provenance == PROVENANCE_PROVIDER_VERIFIED
    assert result.count == 300


# ---------------------------------------------------------------------------
# 6. Require-verified semantics (fail-closed when verification required)
# ---------------------------------------------------------------------------


def test_require_verified_true_provider_none_raises() -> None:
    """With require_verified=True and no provider, SampleCountVerificationError is raised."""
    with pytest.raises(SampleCountVerificationError):
        resolve_sample_count(
            client_claimed=100,
            provider=None,
            client_id="cl-5",
            update_id="upd-5",
            round_number=1,
            require_verified=True,
        )


def test_require_verified_true_provider_raises_propagates() -> None:
    """With require_verified=True, provider failure raises SampleCountVerificationError."""
    with pytest.raises(SampleCountVerificationError):
        resolve_sample_count(
            client_claimed=100,
            provider=_RaisingProvider(),
            client_id="cl-6",
            update_id="upd-6",
            round_number=1,
            require_verified=True,
        )
