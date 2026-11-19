"""Interface between FinSentinel and an external FL coordinator.

Design rationale
----------------
A real FL coordinator manages the global training loop: it selects which
clients participate in each round, distributes the current global model,
and may track per-client metadata such as sample counts declared during
device selection or confirmed by a secure-aggregation protocol.

FinSentinel uses this interface for two purposes:

1. **Sample-count verification** — the coordinator may know how many
   training samples it expected from each client for a given round.
   ``CoordinatorAdapter.get_expected_sample_count()`` exposes that value
   so ``CoordinatorBackedSampleCountProvider`` can feed it into
   ``resolve_sample_count()``.

2. **Client-selection gating** — before accepting an update, the ingestion
   service can call ``is_client_selected()`` to reject updates from clients
   that were never invited to participate in the declared round.

No real coordinator is available during local development or CI.  The
``StubCoordinatorAdapter`` in ``coordination.stub_coordinator`` is the
test double.  It is explicitly *not* a production implementation.

Security notes
--------------
- An adapter must NEVER derive the expected sample count from the client's
  own claim.  It must query an independent source (the coordinator state
  machine, the secure-aggregation log, etc.).
- Returning ``None`` from ``get_expected_sample_count`` is correct when the
  coordinator has no record for that update.  Callers decide how to handle
  an unverifiable count (see ``resolve_sample_count`` ``require_verified``).
- Returning ``None`` from ``is_client_selected`` means "unknown".  Callers
  that require a definitive answer should treat ``None`` as not-selected.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CoordinatorAdapter(Protocol):
    """Read-only interface to an FL coordinator.

    Implementations must query the coordinator's own state; they must not
    return values derived from the client's update envelope.

    Attributes
    ----------
    name:
        Human-readable identifier used in logs and audit messages.
    """

    name: str

    def get_expected_sample_count(
        self,
        *,
        client_id: str,
        update_id: str,
        round_number: int,
    ) -> int | None:
        """Return the server-side expected sample count for this update.

        Returns ``None`` when the coordinator has no record for this
        client/update/round triple (e.g. client was not selected, update
        is unknown, or coordinator is temporarily unreachable).
        """
        ...

    def is_client_selected(
        self,
        *,
        client_id: str,
        round_number: int,
    ) -> bool | None:
        """Return whether this client was selected for the round.

        Returns:
            True  — client was selected.
            False — client was not selected (update should be rejected).
            None  — unknown (coordinator has no record or is unavailable).
        """
        ...


class CoordinatorBackedSampleCountProvider:
    """``SampleCountProvider`` that delegates to a ``CoordinatorAdapter``.

    Bridges the coordinator interface to the sample-count verification
    contract expected by ``resolve_sample_count()``.

    **Client-selection gating (Q4 fix)**
    Before returning an expected count, ``get_verified_count`` calls
    ``is_client_selected``.  Clients that are not selected for the round
    (``False``) or whose selection status is unknown / coordinator unavailable
    (``None``) receive ``None`` from this provider.  ``resolve_sample_count``
    then falls back to ``"client_claimed"`` unless ``require_verified=True``,
    which causes it to raise ``SampleCountVerificationError`` (fail-closed).

    The provider's ``name`` is derived from the adapter so audit messages
    identify both layers.
    """

    def __init__(self, adapter: CoordinatorAdapter) -> None:
        self._adapter = adapter

    @property
    def name(self) -> str:
        return f"coordinator:{self._adapter.name}"

    def get_verified_count(
        self,
        *,
        client_id: str,
        update_id: str,
        round_number: int,
    ) -> int | None:
        """Return the coordinator's expected count, or *None* if unverifiable.

        Resolution order:
        1. Call ``is_client_selected`` — ``False`` or ``None`` (not selected /
           unknown / unavailable) → return *None* immediately.
        2. Only when selection is confirmed (``True``), call
           ``get_expected_sample_count`` and return its result.
        """
        selected = self._adapter.is_client_selected(
            client_id=client_id, round_number=round_number
        )
        if not selected:
            return None
        return self._adapter.get_expected_sample_count(
            client_id=client_id,
            update_id=update_id,
            round_number=round_number,
        )


