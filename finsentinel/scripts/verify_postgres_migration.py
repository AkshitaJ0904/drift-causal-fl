"""Run guarded PostgreSQL migration verification on one disposable database.

This script never creates a database and refuses any database except the
locally hosted, empty `finsentinel_migration_test` database owned by the
non-privileged `finsentinel_migration_test` role. It requires an explicit
environment opt-in and a database comment before it runs migrations.

Running it upgrades from revision 312321b36f52, inserts a legacy approval,
upgrades to head, checks historical NULL evidence and constraints, creates
and aggregates a newly assessed update, runs PostgreSQL-backed tests, then
downgrades to 312321b36f52. Downgrade removes the evidence and sample-count
columns and permanently loses their values. Never use this script against a
deployed or otherwise valuable database.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARENT_REVISION = "312321b36f52"
HEAD_REVISION = "d1e2f3a4b5c6"
EXPECTED_DATABASE = "finsentinel_migration_test"
EXPECTED_ROLE = "finsentinel_migration_test"
EXPECTED_DATABASE_COMMENT = "FINSENTINEL_DISPOSABLE_MIGRATION_TEST"
OPT_IN_VARIABLE = "FINSENTINEL_ALLOW_DISPOSABLE_DB"
OPT_IN_VALUE = "I_UNDERSTAND_DISPOSABLE_DATABASE"
HISTORICAL_CLIENT = "migration-test-legacy-client"
HISTORICAL_UPDATE = "migration-test-legacy-update"
NEW_CLIENT = "migration-test-new-client"
NEW_UPDATE = "migration-test-new-update"
EVIDENCE_COLUMNS = (
    "risk_score",
    "risk_severity",
    "suspicious",
    "anomaly_reasons",
    "detector_version",
    "detector_config",
    "audit_status",
    "audit_failures",
)
ALL_NEW_COLUMNS = ("sample_count", "sample_count_provenance", *EVIDENCE_COLUMNS)


class SafetyCheckError(RuntimeError):
    """Raised when the configured database cannot be proven disposable."""


@dataclass(frozen=True)
class DatabaseConfig:
    user: str
    password: str = field(repr=False)
    host: str = ""
    port: int = 0
    name: str = ""


def validate_environment(values: Mapping[str, str]) -> DatabaseConfig:
    """Require explicit test-only credentials and a loopback target."""
    required = ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise SafetyCheckError(
            "Missing required database environment variables: "
            + ", ".join(missing)
        )

    if values.get(OPT_IN_VARIABLE) != OPT_IN_VALUE:
        raise SafetyCheckError(
            f"Set {OPT_IN_VARIABLE}={OPT_IN_VALUE} only for the disposable test run."
        )

    if values["DB_NAME"] != EXPECTED_DATABASE:
        raise SafetyCheckError(
            f"DB_NAME must be exactly {EXPECTED_DATABASE!r}."
        )
    if values["DB_USER"] != EXPECTED_ROLE:
        raise SafetyCheckError(
            f"DB_USER must be exactly {EXPECTED_ROLE!r}."
        )

    host = values["DB_HOST"].strip().lower()
    if host == "localhost":
        host = "localhost"
    else:
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise SafetyCheckError(
                "DB_HOST must be localhost or a literal loopback IP address."
            ) from exc
        if not address.is_loopback:
            raise SafetyCheckError("DB_HOST must resolve only to loopback.")

    try:
        port = int(values["DB_PORT"])
    except ValueError as exc:
        raise SafetyCheckError("DB_PORT must be an integer from 1 to 65535.") from exc
    if not 1 <= port <= 65535:
        raise SafetyCheckError("DB_PORT must be an integer from 1 to 65535.")

    return DatabaseConfig(
        user=values["DB_USER"],
        password=values["DB_PASSWORD"],
        host=host,
        port=port,
        name=values["DB_NAME"],
    )


def _connect(config: DatabaseConfig):
    import psycopg

    return psycopg.connect(
        host=config.host,
        port=config.port,
        dbname=config.name,
        user=config.user,
        password=config.password,
        sslmode="require",
        connect_timeout=5,
        autocommit=True,
    )


def _verify_database_identity(config: DatabaseConfig) -> None:
    with _connect(config) as connection:
        identity = connection.execute(
            """
            SELECT current_database(), current_user,
                   host(inet_server_addr()), inet_server_port(),
                   pg_is_in_recovery(),
                   shobj_description(db_record.oid, 'pg_database'),
                   owner.rolname, owner.rolsuper, owner.rolcreatedb,
                   owner.rolcreaterole, owner.rolreplication,
                   owner.rolbypassrls,
                   EXISTS (
                       SELECT 1 FROM pg_stat_ssl
                       WHERE pid = pg_backend_pid() AND ssl
                   )
            FROM pg_database AS db_record
            JOIN pg_roles AS owner ON owner.oid = db_record.datdba
            WHERE db_record.datname = current_database()
            """
        ).fetchone()

        if identity is None:
            raise SafetyCheckError("Could not verify the PostgreSQL database identity.")

        (
            database,
            role,
            server_address,
            server_port,
            in_recovery,
            database_comment,
            owner,
            is_superuser,
            can_create_database,
            can_create_role,
            can_replicate,
            can_bypass_rls,
            ssl_enabled,
        ) = identity

        if database != EXPECTED_DATABASE or role != EXPECTED_ROLE or owner != EXPECTED_ROLE:
            raise SafetyCheckError("Connected database, role, or owner did not match.")
        if database_comment != EXPECTED_DATABASE_COMMENT:
            raise SafetyCheckError(
                "Database comment must be exactly "
                f"{EXPECTED_DATABASE_COMMENT!r}."
            )
        if not server_address or not ipaddress.ip_address(server_address).is_loopback:
            raise SafetyCheckError("PostgreSQL server address is not loopback.")
        if server_port != config.port:
            raise SafetyCheckError("Connected PostgreSQL port did not match DB_PORT.")
        if in_recovery:
            raise SafetyCheckError("The target PostgreSQL server is in recovery mode.")
        if any(
            (
                is_superuser,
                can_create_database,
                can_create_role,
                can_replicate,
                can_bypass_rls,
            )
        ):
            raise SafetyCheckError("The test role has privileged PostgreSQL attributes.")
        if not ssl_enabled:
            raise SafetyCheckError(
                "PostgreSQL SSL is not active; the project connection requires SSL."
            )


def _verify_database_is_empty(config: DatabaseConfig) -> None:
    with _connect(config) as connection:
        schemas = connection.execute(
            """
            SELECT nspname FROM pg_namespace
            WHERE nspname NOT IN ('information_schema', 'public')
              AND nspname !~ '^pg_'
            """
        ).fetchall()
        if schemas:
            raise SafetyCheckError("The disposable database has unexpected schemas.")

        objects = connection.execute(
            """
            SELECT count(*) FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
            """
        ).fetchone()[0]
        if objects:
            raise SafetyCheckError(
                "The disposable database is not empty. Use a newly created test database."
            )


def _run(
    command: Sequence[str],
    config: DatabaseConfig,
    *,
    env: Mapping[str, str] | None = None,
) -> None:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=dict(env) if env is not None else os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if config.password:
        output = output.replace(config.password, "<redacted>")
    if output:
        print(output, end="")
    if completed.returncode:
        raise RuntimeError(f"Command failed with exit code {completed.returncode}.")


def _alembic(config: DatabaseConfig, *arguments: str) -> None:
    _run(
        [sys.executable, "-m", "alembic", *arguments],
        config,
    )


def _read_revision(config: DatabaseConfig) -> str:
    with _connect(config) as connection:
        row = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        if row is None:
            raise AssertionError("Alembic revision row is missing.")
        return row[0]


def _insert_legacy_approval(config: DatabaseConfig) -> None:
    with _connect(config) as connection:
        connection.execute(
            """
            INSERT INTO update_approvals
                (client_id, update_id, model_version, round_number,
                 payload_sha256, status, reason)
            VALUES (%s, %s, %s, 1, %s, 'pending_approval', %s)
            """,
            (
                HISTORICAL_CLIENT,
                HISTORICAL_UPDATE,
                "migration-test-model-v1",
                "a" * 64,
                "Legacy row seeded at the migration parent revision.",
            ),
        )


def _verify_migrated_schema_and_legacy_row(config: DatabaseConfig) -> None:
    with _connect(config) as connection:
        if _read_revision(config) != HEAD_REVISION:
            raise AssertionError("Alembic did not reach the expected migration head.")

        columns = connection.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'update_approvals'
            """
        ).fetchall()
        nullable_columns = {name for name, nullable in columns if nullable == "YES"}
        if not set(ALL_NEW_COLUMNS) <= nullable_columns:
            raise AssertionError("New migration columns are not all nullable.")

        legacy = connection.execute(
            """
            SELECT sample_count, risk_score, risk_severity, suspicious,
                   anomaly_reasons, detector_version, detector_config,
                   audit_status, audit_failures
            FROM update_approvals
            WHERE client_id = %s AND update_id = %s
            """,
            (HISTORICAL_CLIENT, HISTORICAL_UPDATE),
        ).fetchone()
        if legacy is None or any(value is not None for value in legacy):
            raise AssertionError("Historical row received invented evidence.")

        constraints = {
            row[0]
            for row in connection.execute(
                """
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'public.update_approvals'::regclass
                """
            ).fetchall()
        }
        expected_constraints = {
            "ck_update_approvals_positive_sample_count",
            "ck_update_approvals_risk_score_range",
            "ck_update_approvals_risk_severity",
            "ck_update_approvals_audit_status",
            "ck_update_approvals_sample_count_provenance",
        }
        if not expected_constraints <= constraints:
            raise AssertionError("One or more migration constraints are missing.")


def _assert_check_constraint_rejects(
    config: DatabaseConfig,
    *,
    update_id: str,
    column: str,
    value: object,
    expected_constraint: str,
) -> None:
    import psycopg

    allowed_columns = {
        "sample_count",
        "sample_count_provenance",
        "risk_score",
        "risk_severity",
        "audit_status",
    }
    if column not in allowed_columns:
        raise AssertionError("Internal test attempted an unknown constraint column.")

    with _connect(config) as connection:
        try:
            with connection.transaction():
                connection.execute(
                    f"""
                    INSERT INTO update_approvals
                        (client_id, update_id, model_version, round_number,
                         payload_sha256, status, reason, {column})
                    VALUES (%s, %s, %s, 1, %s, 'pending_approval', %s, %s)
                    """,
                    (
                        "migration-test-constraint-client",
                        update_id,
                        "migration-test-model-v1",
                        "b" * 64,
                        "Intentional invalid value for disposable constraint test.",
                        value,
                    ),
                )
        except psycopg.errors.CheckViolation as exc:
            if exc.diag.constraint_name != expected_constraint:
                raise AssertionError(
                    "The value failed a different PostgreSQL constraint."
                ) from exc
        else:
            raise AssertionError(f"Constraint {expected_constraint} accepted invalid data.")


def _verify_constraints(config: DatabaseConfig) -> None:
    cases = (
        (
            "sample-count-zero",
            "sample_count",
            0,
            "ck_update_approvals_positive_sample_count",
        ),
        (
            "risk-score-too-high",
            "risk_score",
            101,
            "ck_update_approvals_risk_score_range",
        ),
        (
            "risk-severity-invalid",
            "risk_severity",
            "UNASSESSED",
            "ck_update_approvals_risk_severity",
        ),
        (
            "audit-status-invalid",
            "audit_status",
            "unknown",
            "ck_update_approvals_audit_status",
        ),
        (
            "provenance-invalid",
            "sample_count_provenance",
            "invalid_provenance",
            "ck_update_approvals_sample_count_provenance",
        ),
    )
    for update_id, column, value, constraint in cases:
        _assert_check_constraint_rejects(
            config,
            update_id=update_id,
            column=column,
            value=value,
            expected_constraint=constraint,
        )


def _verify_legacy_approval_is_denied(config: DatabaseConfig) -> None:
    import torch

    from aggregation.service import (
        AggregationRejectedError,
        ApprovedUpdatePayload,
        aggregate_approved_updates,
    )
    from enforcement.approval_service import (
        ApprovalError,
        approve_update,
        is_approved,
    )

    try:
        approve_update(
            client_id=HISTORICAL_CLIENT,
            update_id=HISTORICAL_UPDATE,
            reason="This legacy record has no recorded detection evidence.",
        )
    except ApprovalError:
        pass
    else:
        raise AssertionError("Approval accepted a legacy row without evidence.")

    with _connect(config) as connection:
        connection.execute(
            "UPDATE update_approvals SET status = 'approved' "
            "WHERE client_id = %s AND update_id = %s",
            (HISTORICAL_CLIENT, HISTORICAL_UPDATE),
        )

    if is_approved(
        client_id=HISTORICAL_CLIENT,
        update_id=HISTORICAL_UPDATE,
        model_version="migration-test-model-v1",
        round_number=1,
        payload_sha256="a" * 64,
        sample_count=1,
    ):
        raise AssertionError("Approval gate accepted a legacy row without evidence.")

    payload = b"not-deserialized-before-approval-check"
    try:
        aggregate_approved_updates(
            [
                ApprovedUpdatePayload(
                    client_id=HISTORICAL_CLIENT,
                    update_id=HISTORICAL_UPDATE,
                    model_version="migration-test-model-v1",
                    round_number=1,
                    payload=payload,
                    sample_count=1,
                )
            ],
            expected_state_dict={"weight": torch.zeros(1)},
            model_version="migration-test-model-v1",
            round_number=1,
        )
    except AggregationRejectedError:
        return
    raise AssertionError("Aggregation accepted a legacy row without evidence.")


def _create_and_verify_new_evidence(config: DatabaseConfig) -> None:
    import torch

    from aggregation.service import (
        ApprovedUpdatePayload,
        aggregate_approved_updates,
    )
    from core.model_registry import register_model_schema
    from detection.rule_based import RuleBasedDetectionConfig, detect_update_anomalies
    from enforcement.approval_service import (
        approve_update,
        get_update_record,
        is_approved,
        record_ingestion_audit_result,
        register_validated_update,
    )
    from features.update_features import extract_update_features
    from ingestion.sample_count_provider import PROVENANCE_CLIENT_CLAIMED, SampleCountResult
    from ingestion.serialization import serialize_state_dict

    state_dict = {"weight": torch.tensor([1.0, 2.0], dtype=torch.float32)}
    payload = serialize_state_dict(state_dict)
    digest = hashlib.sha256(payload).hexdigest()
    detector_config = RuleBasedDetectionConfig(max_weight_l2_norm=10.0)
    detection = detect_update_anomalies(
        extract_update_features(state_dict),
        config=detector_config,
    )

    record = register_validated_update(
        client_id=NEW_CLIENT,
        update_id=NEW_UPDATE,
        model_version="migration-test-model-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=7, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=digest,
        risk_score=detection.risk_score,
        risk_severity=detection.severity,
        suspicious=detection.suspicious,
        anomaly_reasons=detection.reasons,
        detector_version="rule-based-v1",
        detector_config=asdict(detector_config),
    )
    if record.audit_status != "pending":
        raise AssertionError("New update did not begin with pending audit status.")

    record_ingestion_audit_result(
        client_id=NEW_CLIENT,
        update_id=NEW_UPDATE,
        audit_status="persisted",
        audit_failures=(),
    )
    approve_update(
        client_id=NEW_CLIENT,
        update_id=NEW_UPDATE,
        reason="Disposable PostgreSQL migration verification approval.",
    )
    register_model_schema(
        model_version="migration-test-model-v1",
        state_dict=state_dict,
    )

    with _connect(config) as connection:
        row = connection.execute(
            """
            SELECT sample_count, payload_sha256, risk_score, risk_severity,
                   suspicious, anomaly_reasons, detector_version,
                   detector_config, audit_status, audit_failures
            FROM update_approvals
            WHERE client_id = %s AND update_id = %s
            """,
            (NEW_CLIENT, NEW_UPDATE),
        ).fetchone()
    if row is None:
        raise AssertionError("New evidence-bearing approval was not persisted.")

    expected: tuple[object, ...] = (
        7,
        digest,
        detection.risk_score,
        detection.severity,
        detection.suspicious,
        list(detection.reasons),
        "rule-based-v1",
        asdict(detector_config),
        "persisted",
        [],
    )
    if row != expected:
        raise AssertionError("Persisted sample count or detector evidence did not match.")

    persisted = get_update_record(client_id=NEW_CLIENT, update_id=NEW_UPDATE)
    if persisted.risk_score is None or persisted.detector_version != "rule-based-v1":
        raise AssertionError("New approval lost its actual detector evidence.")
    if not is_approved(
        client_id=NEW_CLIENT,
        update_id=NEW_UPDATE,
        model_version="migration-test-model-v1",
        round_number=1,
        payload_sha256=digest,
        sample_count=7,
    ):
        raise AssertionError("Exact new approval was not authorized.")
    if is_approved(
        client_id=NEW_CLIENT,
        update_id=NEW_UPDATE,
        model_version="migration-test-model-v1",
        round_number=1,
        payload_sha256=digest,
        sample_count=8,
    ):
        raise AssertionError("Approval was not bound to the recorded sample count.")
    if is_approved(
        client_id=NEW_CLIENT,
        update_id=NEW_UPDATE,
        model_version="migration-test-model-v1",
        round_number=1,
        payload_sha256="f" * 64,
        sample_count=7,
    ):
        raise AssertionError("Approval was not bound to the recorded payload digest.")

    aggregate = aggregate_approved_updates(
        [
            ApprovedUpdatePayload(
                client_id=NEW_CLIENT,
                update_id=NEW_UPDATE,
                model_version="migration-test-model-v1",
                round_number=1,
                payload=payload,
                sample_count=7,
            )
        ],
        expected_state_dict=state_dict,
        model_version="migration-test-model-v1",
        round_number=1,
    )
    if not torch.equal(aggregate["weight"], state_dict["weight"]):
        raise AssertionError("Approved test update did not aggregate as expected.")

    modified_payload = serialize_state_dict(
        {"weight": torch.tensor([1.0, 2.1], dtype=torch.float32)}
    )
    try:
        aggregate_approved_updates(
            [
                ApprovedUpdatePayload(
                    client_id=NEW_CLIENT,
                    update_id=NEW_UPDATE,
                    model_version="migration-test-model-v1",
                    round_number=1,
                    payload=modified_payload,
                    sample_count=7,
                )
            ],
            expected_state_dict=state_dict,
            model_version="migration-test-model-v1",
            round_number=1,
        )
    except Exception as exc:
        from aggregation.service import AggregationRejectedError

        if isinstance(exc, AggregationRejectedError):
            pass
        else:
            raise
    else:
        raise AssertionError("Aggregation accepted a payload with a changed digest.")

    try:
        aggregate_approved_updates(
            [
                ApprovedUpdatePayload(
                    client_id=NEW_CLIENT,
                    update_id=NEW_UPDATE,
                    model_version="migration-test-model-v1",
                    round_number=1,
                    payload=payload,
                    sample_count=8,
                )
            ],
            expected_state_dict=state_dict,
            model_version="migration-test-model-v1",
            round_number=1,
        )
    except Exception as exc:
        from aggregation.service import AggregationRejectedError

        if isinstance(exc, AggregationRejectedError):
            return
        raise
    raise AssertionError("Aggregation accepted a changed sample count.")


def _run_pytest(config: DatabaseConfig) -> None:
    env = os.environ.copy()
    env["ENVIRONMENT"] = "test"
    env["FINSENTINEL_ALLOWED_MODEL_VERSIONS"] = "cnn-v1"
    env["FINSENTINEL_ALLOWED_ROUNDS"] = "1"
    env["FINSENTINEL_MAX_UPDATE_AGE_SECONDS"] = "315360000"
    env["FINSENTINEL_MAX_FUTURE_CLOCK_SKEW_SECONDS"] = "315360000"

    focused = (
        "tests/test_approval_service.py",
        "tests/test_aggregation_service.py",
        "tests/test_detection_ingestion_integration.py",
        "tests/test_ingestion_api.py",
        "tests/test_detection_evidence_migration.py",
    )
    _run(
        [sys.executable, "-m", "pytest", *focused, "-q", "-p", "no:cacheprovider"],
        config,
        env=env,
    )
    _run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        config,
        env=env,
    )


def _verify_downgrade(config: DatabaseConfig) -> None:
    _verify_database_identity(config)
    _alembic(config, "downgrade", PARENT_REVISION)
    with _connect(config) as connection:
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
        if revision != PARENT_REVISION:
            raise AssertionError("Downgrade did not reach the parent revision.")
        remaining = connection.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'update_approvals'
              AND column_name = ANY(%s)
            """,
            (list(ALL_NEW_COLUMNS),),
        ).fetchall()
        if remaining:
            raise AssertionError("Downgrade left new evidence columns behind.")


def run_verification(config: DatabaseConfig) -> None:
    _verify_database_identity(config)
    _verify_database_is_empty(config)

    print(f"Using verified disposable database {EXPECTED_DATABASE!r}.")
    _alembic(config, "upgrade", PARENT_REVISION)
    if _read_revision(config) != PARENT_REVISION:
        raise AssertionError("Could not reach the migration parent revision.")

    _insert_legacy_approval(config)
    _alembic(config, "upgrade", "head")
    reached_head = _read_revision(config) == HEAD_REVISION
    if not reached_head:
        raise AssertionError("Migration did not reach the expected head.")

    try:
        _verify_migrated_schema_and_legacy_row(config)
        _verify_constraints(config)
        _verify_legacy_approval_is_denied(config)
        _create_and_verify_new_evidence(config)
        _run_pytest(config)
    finally:
        _verify_downgrade(config)

    print(
        "Verification finished. The disposable database is at revision "
        f"{PARENT_REVISION}; migration evidence columns were dropped."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute-disposable-test",
        action="store_true",
        help="run destructive migration checks after all safety guards pass",
    )
    args = parser.parse_args()

    if not args.execute_disposable_test:
        parser.error(
            "no database connection is made without --execute-disposable-test"
        )

    try:
        config = validate_environment(os.environ)
        run_verification(config)
    except Exception as exc:
        print(f"PostgreSQL migration verification stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
