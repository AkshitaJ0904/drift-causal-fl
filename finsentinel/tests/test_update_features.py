
"""Tests for federated-learning update feature extraction."""

import pytest
import torch

from features.update_features import extract_update_features


def test_extracts_basic_weight_features():
    state_dict = {
        "layer.weight": torch.tensor([3.0, 4.0]),
        "layer.bias": torch.tensor([0.0]),
    }

    features = extract_update_features(state_dict)

    assert features["weight_element_count"] == 3.0
    assert features["weight_l2_norm"] == pytest.approx(5.0)
    assert features["weight_mean"] == pytest.approx(7.0 / 3.0)
    assert features["weight_min"] == 0.0
    assert features["weight_max"] == 4.0
    assert features["weight_zero_fraction"] == pytest.approx(1.0 / 3.0)


def test_extracts_update_l2_norm_against_reference():
    reference = {
        "layer.weight": torch.tensor([1.0, 2.0]),
    }
    submitted = {
        "layer.weight": torch.tensor([4.0, 6.0]),
    }

    features = extract_update_features(
        submitted,
        reference_state_dict=reference,
    )

    # Difference = [3, 4]; L2 norm = sqrt(3² + 4²) = 5.
    assert features["update_l2_norm"] == pytest.approx(5.0)


def test_rejects_nan_weights():
    state_dict = {
        "layer.weight": torch.tensor([1.0, float("nan")]),
    }

    with pytest.raises(ValueError, match="NaN or infinity"):
        extract_update_features(state_dict)


def test_rejects_infinite_weights():
    state_dict = {
        "layer.weight": torch.tensor([1.0, float("inf")]),
    }

    with pytest.raises(ValueError, match="NaN or infinity"):
        extract_update_features(state_dict)


def test_rejects_empty_state_dict():
    with pytest.raises(ValueError, match="must not be empty"):
        extract_update_features({})


def test_rejects_mismatched_reference_shapes():
    submitted = {
        "layer.weight": torch.tensor([1.0, 2.0]),
    }
    reference = {
        "layer.weight": torch.tensor([1.0]),
    }

    with pytest.raises(ValueError, match="Shape mismatch"):
        extract_update_features(
            submitted,
            reference_state_dict=reference,
        )


def test_rejects_mismatched_reference_tensor_names():
    submitted = {
        "layer.weight": torch.tensor([1.0, 2.0]),
    }
    reference = {
        "other.weight": torch.tensor([1.0, 2.0]),
    }

    with pytest.raises(ValueError, match="names do not match"):
        extract_update_features(
            submitted,
            reference_state_dict=reference,
        )

def test_rejects_non_tensor_entries():
    with pytest.raises(ValueError, match="not a PyTorch tensor"):
        extract_update_features({"layer.weight": [1.0, 2.0]})


def test_rejects_mismatched_reference_dtypes():
    submitted = {
        "layer.weight": torch.tensor([1.0, 2.0], dtype=torch.float32),
    }
    reference = {
        "layer.weight": torch.tensor([1.0, 2.0], dtype=torch.float64),
    }

    with pytest.raises(ValueError, match="Dtype mismatch"):
        extract_update_features(
            submitted,
            reference_state_dict=reference,
        )


def test_calculates_zero_update_norm_for_identical_weights():
    state_dict = {
        "layer.weight": torch.tensor([1.0, 2.0]),
    }

    features = extract_update_features(
        state_dict,
        reference_state_dict=state_dict,
    )

    assert features["update_l2_norm"] == pytest.approx(0.0)


def test_extracts_weight_standard_deviation():
    state_dict = {
        "layer.weight": torch.tensor([1.0, 3.0]),
    }

    features = extract_update_features(state_dict)

    # Population standard deviation of [1, 3] is 1.
    assert features["weight_std"] == pytest.approx(1.0)


def test_extracts_absolute_mean():
    state_dict = {
        "layer.weight": torch.tensor([-2.0, 4.0]),
    }

    features = extract_update_features(state_dict)

    assert features["weight_abs_mean"] == pytest.approx(3.0)
