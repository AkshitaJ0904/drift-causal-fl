"""Trusted sample-count provider interface for ingested FL updates.

Design rationale
----------------
The client-claimed ``sample_count`` is the number the client includes in its
signed update envelope.  It is never independently verified by default — the
server only checks it does not exceed the per-key maximum configured in the
key registry.

This module defines:

* ``SampleCountProvider`` — a Protocol that any server-side verification
  source must implement.  Implementations fetch the count from a trusted
  source (the FL coordinator, a secure aggregation protocol, an independent
  data-plane tracker, etc.) and must NOT return a value derived from the
  client's own claim.

* ``NullSampleCountProvider`` — explicit no-op implementation used when no
  verification source is configured.  It always returns *None* (unavailable).

* ``resolve_sample_count`` — combines the client-claimed count with the
  provider result into a ``SampleCountResult`` that records whether the count
  is ``"client_claimed"`` or ``"provider_verified"``.

Provenance values
-----------------
``PROVENANCE_CLIENT_CLAIMED``
    No independent verification; the value comes directly from the client.
    This is the default when no provider is configured.  It MUST NOT be
    silently re-labelled as trusted by any downstream component.

``PROVENANCE_PROVIDER_VERIFIED``
    A configured provider confirmed the count independently.  The provider's
    value matched the client's claim (mismatch raises ``SampleCountMismatchError``).

Policy enforcement
------------------
Pass ``require_verified=True`` to ``resolve_sample_count`` when the calling
context requires verified provenance.  If no provider is configured, or the
provider cannot verify this specific update, ``SampleCountVerificationError``
is raised, blocking registration fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

PROVENANCE_CLIENT_CLAIMED = "client_claimed"
PROVENANCE_PROVIDER_VERIFIED = "provider_verified"

_VALID_PROVENANCES = frozenset({PROVENANCE_CLIENT_CLAIMED, PROVENANCE_PROVIDER_VERIFIED})


class _ProviderVerifiedSeal:
    """Private sentinel passed only by :func:`resolve_sample_count` when a provider verifies the
    count.

    :class:`SampleCountResult` requires this token when
    ``provenance == PROVENANCE_PROVIDER_VERIFIED``.  Constructing a
    ``PROVENANCE_PROVIDER_VERIFIED`` result without it raises ``ValueError``.

    This is a best-effort trust boundary.  Python has no truly private classes,
    but the leading underscore and the requirement to import a private module
    attribute make accidental or unreviewed misuse obvious at code-review time.
    Any code that imports ``_ProviderVerifiedSeal`` or ``_PROVIDER_VERIFIED_SEAL``
    directly is bypassing the intended contract and must be flagged in review.
    """
    __slots__ = ()


_PROVIDER_VERIFIED_SEAL = _ProviderVerifiedSeal()


class SampleCountVerificationError(ValueError):
    """Raised when verified provenance is required but unavailable.

    Callers that set ``require_verified=True`` must handle this error
    by blocking the update registration (fail-closed behaviour).
    """


class SampleCountMismatchError(ValueError):
    """Raised when the provider's verified count differs from the client's claim.

    This indicates either a misconfigured provider or a dishonest client.
    The update must be rejected.
    """


@dataclass(frozen=True)
class SampleCountResult:
    """Outcome of one sample-count resolution call.

    Attributes
    ----------
    count:
        The resolved sample count to use for approval and aggregation.
    provenance:
        ``PROVENANCE_CLIENT_CLAIMED`` or ``PROVENANCE_PROVIDER_VERIFIED``.
    provider_name:
        Human-readable name of the provider that supplied the verified count,
        or *None* when provenance is ``CLIENT_CLAIMED``.

    Construction
    ------------
    * For client-claimed counts:
      ``SampleCountResult(count=N, provenance=PROVENANCE_CLIENT_CLAIMED)``
    * For provider-verified counts: call :func:`resolve_sample_count` with a
      configured provider.  Direct construction with ``PROVENANCE_PROVIDER_VERIFIED``
      is rejected unless the private ``_seal`` token is supplied by that function.
    """

    count: int
    provenance: str
    provider_name: str | None = None
    _seal: _ProviderVerifiedSeal | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count <= 0:
            raise ValueError(
                f"SampleCountResult.count must be a positive integer, got {self.count!r}."
            )
        if self.provenance not in _VALID_PROVENANCES:
            raise ValueError(
                f"SampleCountResult.provenance must be one of "
                f"{sorted(_VALID_PROVENANCES)!r}, got {self.provenance!r}."
            )
        if (
            self.provenance == PROVENANCE_PROVIDER_VERIFIED
            and self._seal is not _PROVIDER_VERIFIED_SEAL
        ):
            raise ValueError(
                "SampleCountResult with provenance 'provider_verified' may only be "
                "constructed by resolve_sample_count(). "
                "For client-claimed counts use "
                "SampleCountResult(count=N, provenance=PROVENANCE_CLIENT_CLAIMED). "
                "For provider-verified counts call resolve_sample_count() with a "
                "configured provider — do not pass 'provider_verified' directly."
            )


@runtime_checkable
class SampleCountProvider(Protocol):
    """Server-side source of independently verified sample counts.

    Implementations must NOT return a value derived from the client's own
    claim.  They should query a trusted source such as the FL coordinator,
    a secure-aggregation log, or an independent data-plane accounting service.

    ``name`` is used in log messages and stored in ``SampleCountResult``.
    ``get_verified_count`` returns the verified count, or *None* if the
    provider cannot verify this particular update (e.g. it has not been
    registered yet, or the provider is temporarily unavailable).
    """

    @property
    def name(self) -> str: ...

    def get_verified_count(
        self,
        *,
        client_id: str,
        update_id: str,
        round_number: int,
    ) -> int | None:
        """Return the independently verified count, or *None* if unavailable."""
        ...


class NullSampleCountProvider:
    """Explicit no-op provider used when no verification source is configured.

    ``get_verified_count`` always returns *None*.  This makes the absence of a
    real provider explicit and prevents accidental re-use of client values as
    if they were verified.
    """

    name = "null"

    def get_verified_count(
        self,
        *,
        client_id: str,
        update_id: str,
        round_number: int,
    ) -> int | None:
        return None


def resolve_sample_count(
    *,
    client_claimed: int,
    provider: SampleCountProvider | None,
    client_id: str,
    update_id: str,
    round_number: int,
    require_verified: bool = False,
) -> SampleCountResult:
    """Resolve the sample count for an ingested update.

    Resolution order
    ----------------
    1. If *provider* is not *None*, call ``get_verified_count``.
       a. If it returns a positive integer that equals *client_claimed* →
          ``PROVIDER_VERIFIED``.
       b. If it returns a positive integer that differs from *client_claimed* →
          ``SampleCountMismatchError``.
       c. If it raises → treated as unavailable (proceed to step 2), unless
          ``require_verified`` is True in which case the exception propagates
          as ``SampleCountVerificationError``.
       d. If it returns *None* (unavailable) → proceed to step 2.
    2. No verified count available.
       a. If ``require_verified`` is True → ``SampleCountVerificationError``.
       b. Otherwise → ``CLIENT_CLAIMED``.

    Parameters
    ----------
    client_claimed:
        The count the client included in its signed update envelope.
    provider:
        Optional independent verifier.  Pass *None* when none is configured.
    client_id, update_id, round_number:
        Identity of the update being resolved, forwarded to the provider.
    require_verified:
        If True, the function raises rather than return ``CLIENT_CLAIMED``.
    """
    if (
        isinstance(client_claimed, bool)
        or not isinstance(client_claimed, int)
        or client_claimed <= 0
    ):
        raise ValueError("client_claimed must be a positive integer.")

    provider_name: str | None = getattr(provider, "name", None) if provider is not None else None
    verified_count: int | None = None

    if provider is not None:
        try:
            verified_count = provider.get_verified_count(
                client_id=client_id,
                update_id=update_id,
                round_number=round_number,
            )
        except (SampleCountVerificationError, SampleCountMismatchError):
            raise
        except Exception as exc:
            if require_verified:
                raise SampleCountVerificationError(
                    f"Provider {provider_name!r} raised an error and verified "
                    "provenance is required."
                ) from exc
            verified_count = None

    if verified_count is not None:
        if (
            isinstance(verified_count, bool)
            or not isinstance(verified_count, int)
            or verified_count <= 0
        ):
            raise SampleCountMismatchError(
                f"Provider {provider_name!r} returned an invalid count: {verified_count!r}."
            )
        if verified_count != client_claimed:
            raise SampleCountMismatchError(
                f"Provider {provider_name!r} returned {verified_count} but "
                f"client claimed {client_claimed}."
            )
        return SampleCountResult(
            count=verified_count,
            provenance=PROVENANCE_PROVIDER_VERIFIED,
            provider_name=provider_name,
            _seal=_PROVIDER_VERIFIED_SEAL,
        )

    if require_verified:
        if provider is not None:
            msg = (
                f"Provider {provider_name!r} could not verify this update; "
                "verified provenance is required."
            )
        else:
            msg = (
                "sample_count_provider: no provider configured; "
                "verified provenance is required."
            )
        raise SampleCountVerificationError(msg)

    return SampleCountResult(
        count=client_claimed,
        provenance=PROVENANCE_CLIENT_CLAIMED,
        provider_name=None,
    )
