
"""Tests for safe NPZ model-weight serialization."""

import pytest
import torch

from ingestion.serialization import (
    SerializationError,
    deserialize_state_dict,
    serialize_state_dict,
)


def test_round_trip_preserves_tensor_values_shapes_and_dtypes():
    original = {
        "layer.weight": torch.tensor([[1.0, 2.0], [3.0, 4.0]], dtype=torch.float32),
        "layer.bias": torch.tensor([5.0, 6.0], dtype=torch.float64),
        "num_batches_tracked": torch.tensor(7, dtype=torch.int64),
    }

    payload = serialize_state_dict(original)
    restored = deserialize_state_dict(payload)

    assert set(restored) == set(original)

    for name, tensor in original.items():
        assert restored[name].shape == tensor.shape
        assert restored[name].dtype == tensor.dtype
        assert torch.equal(restored[name], tensor)


def test_serialized_payload_is_bytes():
    payload = serialize_state_dict({"weight": torch.tensor([1.0, 2.0])})
    assert isinstance(payload, bytes)
    assert payload


def test_rejects_empty_payload():
    with pytest.raises(SerializationError, match="non-empty bytes"):
        deserialize_state_dict(b"")


def test_rejects_payload_over_size_limit():
    with pytest.raises(SerializationError, match="size limit"):
        deserialize_state_dict(b"x" * 100, max_total_bytes=10)


def test_rejects_invalid_npz_payload():
    with pytest.raises(SerializationError):
        deserialize_state_dict(b"not a valid NPZ archive")



def test_rejects_nan_before_serialization():
    state_dict = {"weight": torch.tensor([1.0, float("nan")])}

    with pytest.raises(SerializationError, match="NaN or infinite values"):
        serialize_state_dict(state_dict)



def test_rejects_unsupported_manifest_version():
    import io
    import json

    import numpy as np

    buffer = io.BytesIO()
    manifest = {
        "format_version": 999,
        "tensor_count": 1,
        "tensors": [
            {
                "name": "weight",
                "archive_key": "tensor_000000",
                "shape": [1],
                "dtype": "<f4",
            }
        ],
    }

    np.savez_compressed(
        buffer,
        __manifest__=np.frombuffer(
            json.dumps(manifest).encode("utf-8"),
            dtype=np.uint8,
        ),
        tensor_000000=np.array([1.0], dtype=np.float32),
    )

    with pytest.raises(SerializationError, match="version"):
        deserialize_state_dict(buffer.getvalue())
