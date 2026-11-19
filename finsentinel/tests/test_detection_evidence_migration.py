"""Tests for historical detection-evidence migration declarations.

These tests inspect the migration operations only. They do not execute or
verify the migration against PostgreSQL.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "a9b11270d3c1_add_structured_detection_evidence.py"
)
SPEC = spec_from_file_location("detection_evidence_migration", MIGRATION_PATH)
assert SPEC is not None and SPEC.loader is not None
MIGRATION = module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def test_historical_evidence_columns_are_nullable_without_defaults(monkeypatch):
    added_columns = {}

    def record_column(table_name, column):
        assert table_name == "update_approvals"
        added_columns[column.name] = column

    operations = SimpleNamespace(
        add_column=record_column,
        create_check_constraint=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(MIGRATION, "op", operations)

    MIGRATION.upgrade()

    evidence_columns = {
        "risk_score",
        "risk_severity",
        "suspicious",
        "anomaly_reasons",
        "detector_version",
        "detector_config",
        "audit_status",
        "audit_failures",
    }
    assert evidence_columns <= added_columns.keys()
    for name in evidence_columns:
        assert added_columns[name].nullable is True
        assert added_columns[name].server_default is None

