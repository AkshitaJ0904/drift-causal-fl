"""Tests for pre-serialization state-dictionary validation."""
import torch
from features.update_validation import validate_state_dict


def test_valid_state_dict_is_accepted() -> None:
    state = {
        "weight": torch.tensor([[0.1, 0.2], [0.3, 0.4]]),
        "bias": torch.tensor([0.0, 0.1]),
    }

    result = validate_state_dict(state)

    assert result.accepted
    assert result.tensor_count == 2
    assert result.parameter_count == 6
    assert result.non_finite_count == 0


def test_nan_is_rejected() -> None:
    state = {"weight": torch.tensor([0.1, float("nan")])}

    result = validate_state_dict(state)

    assert not result.accepted
    assert "NaN or infinite" in result.reason
    assert result.non_finite_count == 1


def test_infinity_is_rejected() -> None:
    state = {"weight": torch.tensor([0.1, float("inf")])}

    result = validate_state_dict(state)

    assert not result.accepted
    assert result.non_finite_count == 1


def test_expected_shape_mismatch_is_rejected() -> None:
    state = {"weight": torch.zeros(2, 3)}
    expected = {"weight": torch.zeros(2, 2)}

    result = validate_state_dict(state, expected_state_dict=expected)

    assert not result.accepted
    assert "shape mismatch" in result.reason


def test_expected_tensor_names_must_match() -> None:
    state = {"unexpected.weight": torch.zeros(2)}
    expected = {"weight": torch.zeros(2)}

    result = validate_state_dict(state, expected_state_dict=expected)

    assert not result.accepted
    assert "Tensor names" in result.reason


def test_model_size_limit_is_enforced() -> None:
    state = {"weight": torch.zeros(100, dtype=torch.float32)}

    result = validate_state_dict(state, max_total_bytes=100)

    assert not result.accepted
    assert "size limit" in result.reason


def test_non_tensor_entry_is_rejected() -> None:
    state = {"weight": "not a tensor"}

    result = validate_state_dict(state)

    assert not result.accepted
    assert "not a PyTorch tensor" in result.reason
