"""In-memory stub coordinator for testing.

WARNING: This is NOT a production FL coordinator.  It stores registration
data in memory only, has no persistence, no security, and does not implement
any part of the federated learning protocol.  Use it exclusively in unit
tests and isolated integration tests.  Never configure it for a service that
handles real client updates.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _RoundEntry:
    client_id: str
    round_number: int
    sample_count: int | None = None
    update_id: str | None = None


class StubCoordinatorAdapter:
    """Deterministic in-memory coordinator for local tests.

    Usage::

        stub = StubCoordinatorAdapter()
        stub.register_participation(client_id="c1", round_number=1, sample_count=200)
        stub.register_participation(
            client_id="c2", round_number=1, sample_count=150,
            update_id="upd-abc",   # optional: bind to a specific update_id
        )

    ``is_client_selected`` returns ``True`` for any client that has been
    registered for the given round, ``False`` for clients registered for a
    *different* round, and ``None`` for completely unknown clients.

    ``get_expected_sample_count`` returns the registered ``sample_count``,
    or ``None`` when no registration exists.  If a registration was made
    with an explicit ``update_id``, it matches only when ``update_id``
    matches; a round-level registration (no ``update_id``) matches any
    ``update_id`` for that client and round.

    This stub is intentionally simplistic.  It has no thread safety, no
    per-round model distribution, and no protocol simulation.  It is a
    "honest test double": it behaves the way a real coordinator would for
    the cases it was set up to cover, and returns ``None`` / ``False`` for
    everything else rather than fabricating data.
    """

    name = "stub-coordinator"

    def __init__(self) -> None:
        self._entries: list[_RoundEntry] = []

    def register_participation(
        self,
        *,
        client_id: str,
        round_number: int,
        sample_count: int | None = None,
        update_id: str | None = None,
    ) -> None:
        """Pre-load a client participation record for use in tests.

        Parameters
        ----------
        client_id:
            The client identifier.
        round_number:
            The training round the client participated in.
        sample_count:
            The server-side expected sample count.  ``None`` means the
            coordinator knows the client participated but has no sample count.
        update_id:
            Optional.  If supplied, this entry applies only to the specific
            update.  If omitted, the entry applies to any update from this
            client in this round.
        """
        if isinstance(sample_count, bool) or (
            sample_count is not None and (not isinstance(sample_count, int) or sample_count <= 0)
        ):
            raise ValueError(
                "sample_count must be a positive integer or None, "
                f"got {sample_count!r}."
            )
        self._entries.append(
            _RoundEntry(
                client_id=client_id,
                round_number=round_number,
                sample_count=sample_count,
                update_id=update_id,
            )
        )

    def _find_entry(
        self,
        *,
        client_id: str,
        round_number: int,
        update_id: str | None = None,
    ) -> _RoundEntry | None:
        """Return the most-specific matching entry, or None."""
        specific: _RoundEntry | None = None
        general: _RoundEntry | None = None
        for entry in self._entries:
            if entry.client_id != client_id or entry.round_number != round_number:
                continue
            if update_id is not None and entry.update_id == update_id:
                specific = entry
            elif entry.update_id is None:
                general = entry
        return specific if specific is not None else general

    def get_expected_sample_count(
        self,
        *,
        client_id: str,
        update_id: str,
        round_number: int,
    ) -> int | None:
        """Return the registered expected sample count, or None."""
        entry = self._find_entry(
            client_id=client_id,
            round_number=round_number,
            update_id=update_id,
        )
        if entry is None:
            return None
        return entry.sample_count

    def is_client_selected(
        self,
        *,
        client_id: str,
        round_number: int,
    ) -> bool | None:
        """True if selected for this round; False if known but wrong round; None if unknown."""
        for_this_round = self._find_entry(client_id=client_id, round_number=round_number)
        if for_this_round is not None:
            return True
        if any(e.client_id == client_id for e in self._entries):
            return False
        return None

    def clear(self) -> None:
        """Remove all registered entries (useful between test cases)."""
        self._entries.clear()
