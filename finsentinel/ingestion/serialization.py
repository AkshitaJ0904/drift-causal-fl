
"""Safe NumPy-based serialization for federated-learning model weights."""

import io
import json
import zipfile
from collections.abc import Mapping
from typing import Any

import numpy as np
import torch
from torch import Tensor

from features.update_validation import validate_state_dict

MANIFEST_KEY = "__manifest__"
FORMAT_VERSION = 1
DEFAULT_MAX_TENSORS = 10_000
DEFAULT_MAX_TOTAL_BYTES = 100_000_000


class SerializationError(ValueError):
    """Raised when model weights cannot be safely serialized or parsed."""


def serialize_state_dict(
    state_dict: Mapping[str, Tensor],
    *,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> bytes:
    """Serialize validated tensors to an NPZ byte payload with a JSON manifest."""
    result = validate_state_dict(
        state_dict,
        max_total_bytes=max_total_bytes,
    )
    if not result.accepted:
        raise SerializationError(result.reason)

    arrays: dict[str, np.ndarray[Any, Any]] = {}
    manifest_tensors: list[dict[str, Any]] = []

    for index, (name, tensor) in enumerate(state_dict.items()):
        archive_key = f"tensor_{index:06d}"

        try:
            array = tensor.detach().to(device="cpu").contiguous().numpy()
        except (TypeError, RuntimeError) as exc:
            raise SerializationError(
                f"Tensor {name!r} cannot be represented as a NumPy array."
            ) from exc

        if array.dtype.hasobject:
            raise SerializationError(f"Tensor {name!r} has an unsupported object dtype.")

        arrays[archive_key] = array
        manifest_tensors.append(
            {
                "name": name,
                "archive_key": archive_key,
                "shape": list(array.shape),
                "dtype": array.dtype.str,
            }
        )

    manifest = {
        "format_version": FORMAT_VERSION,
        "tensor_count": len(manifest_tensors),
        "tensors": manifest_tensors,
    }
    manifest_bytes = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    arrays[MANIFEST_KEY] = np.frombuffer(manifest_bytes, dtype=np.uint8)

    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    payload = buffer.getvalue()

    # Bound the resulting transport payload as well.
    if len(payload) > max_total_bytes:
        raise SerializationError("Serialized payload exceeds the configured size limit.")

    return payload


def deserialize_state_dict(
    payload: bytes,
    *,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_tensors: int = DEFAULT_MAX_TENSORS,
) -> dict[str, Tensor]:
    """Parse an NPZ payload without pickle and reconstruct CPU tensors."""
    if not isinstance(payload, bytes) or not payload:
        raise SerializationError("Payload must be non-empty bytes.")

    if max_total_bytes <= 0 or max_tensors <= 0:
        raise SerializationError("Configured limits must be positive.")

    if len(payload) > max_total_bytes:
        raise SerializationError("Payload exceeds the configured size limit.")

    # Inspect ZIP metadata before NumPy expands any compressed arrays.
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]

            if len(names) != len(set(names)):
                raise SerializationError("Archive contains duplicate entries.")

            if MANIFEST_KEY + ".npy" not in names:
                raise SerializationError("Archive is missing its manifest.")

            if any(entry.file_size > max_total_bytes for entry in entries):
                raise SerializationError("An archive entry exceeds the size limit.")

            total_uncompressed = sum(entry.file_size for entry in entries)
            if total_uncompressed > max_total_bytes:
                raise SerializationError("Uncompressed archive exceeds the size limit.")

            if any(entry.flag_bits & 0x1 for entry in entries):
                raise SerializationError("Encrypted ZIP entries are not supported.")

            if any(not name.endswith(".npy") for name in names):
                raise SerializationError("Archive contains an unexpected file.")

    except (zipfile.BadZipFile, OSError) as exc:
        raise SerializationError("Payload is not a valid NPZ archive.") from exc

    try:
        with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
            if MANIFEST_KEY not in archive.files:
                raise SerializationError("Archive is missing its manifest.")

            manifest_array = archive[MANIFEST_KEY]
            if manifest_array.dtype != np.uint8 or manifest_array.ndim != 1:
                raise SerializationError("Manifest has an invalid representation.")

            manifest = json.loads(manifest_array.tobytes().decode("utf-8"))

            if not isinstance(manifest, dict):
                raise SerializationError("Manifest must be a JSON object.")

            if manifest.get("format_version") != FORMAT_VERSION:
                raise SerializationError("Unsupported serialization format version.")

            entries = manifest.get("tensors")
            if not isinstance(entries, list) or not entries:
                raise SerializationError("Manifest must contain a non-empty tensor list.")

            if len(entries) > max_tensors:
                raise SerializationError("Tensor count exceeds the configured limit.")

            if manifest.get("tensor_count") != len(entries):
                raise SerializationError("Manifest tensor count does not match.")

            expected_archive_keys = {MANIFEST_KEY}
            result: dict[str, Tensor] = {}

            for item in entries:
                if not isinstance(item, dict):
                    raise SerializationError("Invalid tensor manifest entry.")

                name = item.get("name")
                key = item.get("archive_key")
                shape = item.get("shape")
                dtype = item.get("dtype")

                if not isinstance(name, str) or not name:
                    raise SerializationError("Tensor name must be a non-empty string.")

                if name in result:
                    raise SerializationError("Manifest contains duplicate tensor names.")

                if (
                    not isinstance(key, str)
                    or not key.startswith("tensor_")
                    or key == MANIFEST_KEY
                ):
                    raise SerializationError("Invalid tensor archive key.")

                if key in expected_archive_keys:
                    raise SerializationError("Manifest contains duplicate archive keys.")

                if (
                    not isinstance(shape, list)
                    or any(type(dim) is not int or dim < 0 for dim in shape)
                ):
                    raise SerializationError("Tensor shape is invalid.")

                if not isinstance(dtype, str):
                    raise SerializationError("Tensor dtype is invalid.")

                expected_archive_keys.add(key)

                if key not in archive.files:
                    raise SerializationError(f"Missing tensor data for {name!r}.")

                array = archive[key]

                if array.dtype.hasobject:
                    raise SerializationError("Object arrays are not supported.")

                if array.dtype.str != dtype:
                    raise SerializationError(f"Dtype mismatch for tensor {name!r}.")

                if list(array.shape) != shape:
                    raise SerializationError(f"Shape mismatch for tensor {name!r}.")

                # Copy into independent memory before the NPZ archive is closed.
                result[name] = torch.from_numpy(np.array(array, copy=True))

            if set(archive.files) != expected_archive_keys:
                raise SerializationError("Archive contains unlisted tensor data.")

            return result

    except SerializationError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        EOFError,
        zipfile.BadZipFile,
    ) as exc:
        raise SerializationError("Payload or manifest is malformed.") from exc
