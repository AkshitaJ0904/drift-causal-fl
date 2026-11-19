"""Coordinator adapter: interface between FinSentinel and an FL coordinator."""

from coordination.coordinator_adapter import (
    CoordinatorAdapter,
    CoordinatorBackedSampleCountProvider,
)
from coordination.stub_coordinator import StubCoordinatorAdapter

__all__ = [
    "CoordinatorAdapter",
    "CoordinatorBackedSampleCountProvider",
    "StubCoordinatorAdapter",
]
