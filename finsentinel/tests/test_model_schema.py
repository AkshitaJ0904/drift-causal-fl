
"""Tests for trusted global-model schema validation."""

import torch

from features.model_schema import validate_model_schema


def expected_model():
    return {
        "layer.weight": torch.zeros((2, 3), dtype=torch.float32),
        "layer.bias": torch.zeros(2, dtype=torch.float32),
    }


def test_accepts_matching_model_schema():
    submitted = {
        "layer.weight": torch.ones((2, 3), dtype=torch.float32),
        "layer.bias": torch.ones(2, dtype=torch.float32),
    }

    result = validate_model_schema(submitted, expected_model())

    assert result.accepted is True
    assert result.tensor_count == 2


def test_rejects_missing_tensor():
    submitted = {
        "layer.weight": torch.ones((2, 3), dtype=torch.float32),
    }

    result = validate_model_schema(submitted, expected_model())

    assert result.accepted is False
    assert "names" in result.reason.lower()


def test_rejects_unexpected_tensor():
    submitted = {
        "layer.weight": torch.ones((2, 3), dtype=torch.float32),
        "layer.bias": torch.ones(2, dtype=torch.float32),
        "unexpected": torch.ones(1),
    }

    result = validate_model_schema(submitted, expected_model())

    assert result.accepted is False
    assert "names" in result.reason.lower()


def test_rejects_shape_mismatch():
    submitted = {
        "layer.weight": torch.ones((3, 2), dtype=torch.float32),
        "layer.bias": torch.ones(2, dtype=torch.float32),
    }

    result = validate_model_schema(submitted, expected_model())

    assert result.accepted is False
    assert "shape" in result.reason.lower()


def test_rejects_dtype_mismatch():
    submitted = {
        "layer.weight": torch.ones((2, 3), dtype=torch.float64),
        "layer.bias": torch.ones(2, dtype=torch.float32),
    }

    result = validate_model_schema(submitted, expected_model())

    assert result.accepted is False
    assert "dtype" in result.reason.lower()


def test_rejects_non_finite_weights():
    submitted = {
        "layer.weight": torch.tensor(
            [[1.0, float("nan"), 2.0], [3.0, 4.0, 5.0]]
        ),
        "layer.bias": torch.ones(2, dtype=torch.float32),
    }

    result = validate_model_schema(submitted, expected_model())

    assert result.accepted is False
    assert "NaN" in result.reason or "infinite" in result.reason
