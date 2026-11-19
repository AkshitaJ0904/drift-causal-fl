"""Tests for the durable DB-backed model schema registry (core/model_registry.py)."""

import pytest
import torch
from sqlalchemy.exc import SQLAlchemyError

from core.model_registry import (
    ModelSchema,
    ModelSchemaNotFoundError,
    RegistryUnavailableError,
    clear_model_schemas,
    get_model_schema,
    register_model_schema,
)

# ---------------------------------------------------------------------------
# Shared state dicts
# ---------------------------------------------------------------------------


def _make_state_dict(shape_a=(10, 5), shape_b=(5,)) -> dict:
    return {
        "weight": torch.zeros(*shape_a),
        "bias": torch.zeros(*shape_b),
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_model_schemas()
    yield
    clear_model_schemas()


# ---------------------------------------------------------------------------
# Registration and retrieval
# ---------------------------------------------------------------------------


def test_register_and_retrieve_schema() -> None:
    state_dict = _make_state_dict()
    register_model_schema("cnn-v1", state_dict)

    schema = get_model_schema("cnn-v1")

    assert isinstance(schema, ModelSchema)
    assert schema.model_version == "cnn-v1"
    assert set(schema.tensor_specs.keys()) == {"weight", "bias"}


def test_tensor_specs_shapes_are_tuples_after_json_roundtrip() -> None:
    """Shapes must come back as tuples, not lists (JSON stores arrays)."""
    register_model_schema("cnn-v2", _make_state_dict(shape_a=(64, 128), shape_b=(64,)))

    schema = get_model_schema("cnn-v2")

    for name, (shape, dtype) in schema.tensor_specs.items():
        assert isinstance(shape, tuple), (
            f"tensor_specs[{name!r}] shape is {type(shape).__name__}, expected tuple"
        )
        assert isinstance(dtype, str)


def test_weight_shape_matches_original() -> None:
    register_model_schema("cnn-v3", _make_state_dict(shape_a=(32, 16), shape_b=(32,)))
    schema = get_model_schema("cnn-v3")

    weight_shape, _ = schema.tensor_specs["weight"]
    bias_shape, _ = schema.tensor_specs["bias"]

    assert weight_shape == (32, 16)
    assert bias_shape == (32,)


def test_dtype_preserved_as_string() -> None:
    register_model_schema("cnn-v4", _make_state_dict())
    schema = get_model_schema("cnn-v4")

    _, dtype = schema.tensor_specs["weight"]
    assert isinstance(dtype, str)
    assert "float" in dtype.lower()


# ---------------------------------------------------------------------------
# Not-found error
# ---------------------------------------------------------------------------


def test_get_unknown_schema_raises_model_schema_not_found() -> None:
    with pytest.raises(ModelSchemaNotFoundError, match="no-such-version"):
        get_model_schema("no-such-version")


# ---------------------------------------------------------------------------
# Validation on register
# ---------------------------------------------------------------------------


def test_register_empty_model_version_raises() -> None:
    with pytest.raises(ValueError, match="model_version"):
        register_model_schema("", _make_state_dict())


def test_register_blank_model_version_raises() -> None:
    with pytest.raises(ValueError, match="model_version"):
        register_model_schema("   ", _make_state_dict())


def test_register_empty_state_dict_raises() -> None:
    with pytest.raises(ValueError, match="state_dict"):
        register_model_schema("cnn-v1", {})


# ---------------------------------------------------------------------------
# UPSERT — schema update
# ---------------------------------------------------------------------------


def test_register_same_version_updates_tensor_specs() -> None:
    register_model_schema("model-v1", _make_state_dict(shape_a=(10, 5)))

    new_state = {"weight": torch.zeros(20, 10), "bias": torch.zeros(20)}
    register_model_schema("model-v1", new_state)

    schema = get_model_schema("model-v1")
    weight_shape, _ = schema.tensor_specs["weight"]
    assert weight_shape == (20, 10)


def test_register_multiple_versions_independent() -> None:
    register_model_schema("alpha", _make_state_dict(shape_a=(2, 3)))
    register_model_schema("beta", _make_state_dict(shape_a=(4, 5)))

    alpha = get_model_schema("alpha")
    beta = get_model_schema("beta")

    assert alpha.tensor_specs["weight"][0] == (2, 3)
    assert beta.tensor_specs["weight"][0] == (4, 5)


# ---------------------------------------------------------------------------
# DB failure (fail-closed)
# ---------------------------------------------------------------------------


class _FailingSession:
    def __enter__(self):
        raise SQLAlchemyError("simulated DB failure")

    def __exit__(self, *args):
        pass


def test_db_failure_on_get_raises_registry_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("core.model_registry.SessionLocal", lambda: _FailingSession())
    with pytest.raises(RegistryUnavailableError):
        get_model_schema("any-version")


def test_db_failure_on_register_raises_registry_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("core.model_registry.SessionLocal", lambda: _FailingSession())
    with pytest.raises(RegistryUnavailableError):
        register_model_schema("cnn-vX", _make_state_dict())


# ---------------------------------------------------------------------------
# Clear (environment guard)
# ---------------------------------------------------------------------------


def test_clear_removes_all_schemas() -> None:
    register_model_schema("v1", _make_state_dict())
    register_model_schema("v2", _make_state_dict())

    clear_model_schemas()

    with pytest.raises(ModelSchemaNotFoundError):
        get_model_schema("v1")
    with pytest.raises(ModelSchemaNotFoundError):
        get_model_schema("v2")


def test_clear_outside_safe_environment_raises(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="production"):
        clear_model_schemas()


# ---------------------------------------------------------------------------
# Persistence across lookups
# ---------------------------------------------------------------------------


def test_schema_persists_across_multiple_lookups() -> None:
    register_model_schema("persist-v1", _make_state_dict(shape_a=(8, 4)))

    schema_a = get_model_schema("persist-v1")
    schema_b = get_model_schema("persist-v1")

    assert schema_a.model_version == schema_b.model_version
    assert schema_a.tensor_specs == schema_b.tensor_specs
