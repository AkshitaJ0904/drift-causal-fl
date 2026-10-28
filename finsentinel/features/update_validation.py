
"""Pre-serialization validation for federated-learning model weights."""

from collections.abc import Mapping
from dataclasses import dataclass

import torch
from torch import Tensor


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating an in-memory model state dictionary."""

    accepted: bool
    reason: str
    tensor_count: int
    parameter_count: int
    total_bytes: int
    non_finite_count: int


def validate_state_dict(
    state_dict: Mapping[str, Tensor],
    *,
    expected_state_dict: Mapping[str, Tensor] | None = None,
    max_total_bytes: int = 100_000_000,
) -> ValidationResult:
    """Validate model weights before serialization.

    If expected_state_dict is provided, tensor names and shapes must match.
    This function does not modify the supplied tensors.
    """
    def reject(
        reason: str,
        *,
        tensor_count: int = 0,
        parameter_count: int = 0,
        total_bytes: int = 0,
        non_finite_count: int = 0,
    ) -> ValidationResult:
        return ValidationResult(
            accepted=False,
            reason=reason,
            tensor_count=tensor_count,
            parameter_count=parameter_count,
            total_bytes=total_bytes,
            non_finite_count=non_finite_count,
        )

    if not isinstance(state_dict, Mapping) or not state_dict:
        return reject("State dictionary must be a non-empty mapping.")

    if max_total_bytes <= 0:
        return reject("max_total_bytes must be positive.")

    if expected_state_dict is not None:
        if set(state_dict.keys()) != set(expected_state_dict.keys()):
            return reject("Tensor names do not match the expected model.")

    tensor_count = 0
    parameter_count = 0
    total_bytes = 0
    non_finite_count = 0

    for name, tensor in state_dict.items():
        if not isinstance(name, str) or not name:
            return reject("Tensor names must be non-empty strings.")

        if not isinstance(tensor, Tensor):
            return reject(f"Entry {name!r} is not a PyTorch tensor.")

        if tensor.layout != torch.strided:
            return reject(f"Tensor {name!r} has an unsupported layout.")

        if tensor.is_complex():
            return reject(f"Tensor {name!r} has an unsupported complex dtype.")

        if tensor.is_quantized:
            return reject(f"Tensor {name!r} is quantized and unsupported.")

        if expected_state_dict is not None:
            expected_tensor = expected_state_dict[name]

            if not isinstance(expected_tensor, Tensor):
                return reject(
                    f"Expected model entry {name!r} is not a tensor."
                )

            if tensor.shape != expected_tensor.shape:
                return reject(
                    f"Tensor {name!r} has a shape mismatch."
                )

            if tensor.dtype != expected_tensor.dtype:
                return reject(
                    f"Tensor {name!r} has a dtype mismatch."
                )

        tensor_count += 1
        parameter_count += tensor.numel()
        total_bytes += tensor.numel() * tensor.element_size()

        if total_bytes > max_total_bytes:
            return reject(
                "Model exceeds the configured size limit.",
                tensor_count=tensor_count,
                parameter_count=parameter_count,
                total_bytes=total_bytes,
            )

        # Check numerical validity only for floating-point tensors.
        if tensor.is_floating_point():
            finite_mask = torch.isfinite(tensor)
            invalid_count = int((~finite_mask).sum().item())
            non_finite_count += invalid_count

            if invalid_count:
                return reject(
                    f"Tensor {name!r} contains NaN or infinite values.",
                    tensor_count=tensor_count,
                    parameter_count=parameter_count,
                    total_bytes=total_bytes,
                    non_finite_count=non_finite_count,
                )

    return ValidationResult(
        accepted=True,
        reason="State dictionary passed structural and numerical checks.",
        tensor_count=tensor_count,
        parameter_count=parameter_count,
        total_bytes=total_bytes,
        non_finite_count=non_finite_count,
    )
