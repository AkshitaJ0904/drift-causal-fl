
"""Feature extraction from federated-learning model updates."""

from collections.abc import Mapping

import numpy as np
import torch
from torch import Tensor


def extract_update_features(
    state_dict: Mapping[str, Tensor],
    *,
    reference_state_dict: Mapping[str, Tensor] | None = None,
) -> dict[str, float]:
    """Extract basic statistical features from model weights.

    If a reference state_dict is supplied, also calculate the L2 norm
    of the difference between the submitted weights and reference weights.

    This function extracts signals for detection; it does not decide
    whether an update is malicious.
    """
    if not state_dict:
        raise ValueError("state_dict must not be empty.")

    flattened_tensors: list[Tensor] = []

    for name, tensor in state_dict.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Tensor names must be non-empty strings.")

        if not isinstance(tensor, Tensor):
            raise ValueError(f"Entry {name!r} is not a PyTorch tensor.")

        if tensor.layout != torch.strided or tensor.is_complex() or tensor.is_quantized:
            raise ValueError(f"Tensor {name!r} has an unsupported type or layout.")

        if tensor.is_floating_point():
            if not torch.isfinite(tensor).all().item():
                raise ValueError(f"Tensor {name!r} contains NaN or infinity.")

            flattened_tensors.append(
                tensor.detach().to(device="cpu", dtype=torch.float64).reshape(-1)
            )

    if not flattened_tensors:
        raise ValueError("No floating-point tensors were found.")

    weights = torch.cat(flattened_tensors)

    features: dict[str, float] = {
        "weight_element_count": float(weights.numel()),
        "weight_l2_norm": float(torch.linalg.vector_norm(weights).item()),
        "weight_mean": float(weights.mean().item()),
        "weight_std": float(weights.std(unbiased=False).item()),
        "weight_min": float(weights.min().item()),
        "weight_max": float(weights.max().item()),
        "weight_abs_mean": float(weights.abs().mean().item()),
        "weight_zero_fraction": float((weights == 0).to(torch.float64).mean().item()),
    }

    if reference_state_dict is not None:
        if set(state_dict.keys()) != set(reference_state_dict.keys()):
            raise ValueError("Submitted and reference tensor names do not match.")

        difference_parts: list[Tensor] = []

        for name, tensor in state_dict.items():
            reference = reference_state_dict[name]

            if not isinstance(reference, Tensor):
                raise ValueError(f"Reference entry {name!r} is not a tensor.")

            if tensor.shape != reference.shape:
                raise ValueError(f"Shape mismatch for tensor {name!r}.")

            if tensor.dtype != reference.dtype:
                raise ValueError(f"Dtype mismatch for tensor {name!r}.")

            if tensor.is_floating_point():
                if not torch.isfinite(reference).all().item():
                    raise ValueError(
                        f"Reference tensor {name!r} contains NaN or infinity."
                    )

                difference_parts.append(
                    (
                        tensor.detach().to(device="cpu", dtype=torch.float64)
                        - reference.detach().to(device="cpu", dtype=torch.float64)
                    ).reshape(-1)
                )

        if difference_parts:
            difference = torch.cat(difference_parts)
            features["update_l2_norm"] = float(
                torch.linalg.vector_norm(difference).item()
            )
        else:
            features["update_l2_norm"] = 0.0

    # Ensure the output can be consumed by standard ML pipelines.
    if not all(np.isfinite(value) for value in features.values()):
        raise ValueError("Feature extraction produced a non-finite value.")

    return features
