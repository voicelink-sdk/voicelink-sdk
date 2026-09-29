"""Shared base for all control-plane resources.

A *resource* groups the actions on one kind of thing (bots, trunks, routing, calls,
DIDs). Each resource is given the client so it can reach the shared transport and the
default ``client_id`` used for reseller-scoped requests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .._transport import Transport
    from ..client import VoiceLinkClient


class Resource:
    """Base class holding a reference to the owning client and its transport."""

    def __init__(self, client: VoiceLinkClient) -> None:
        self._client = client
        self._transport: Transport = client._transport

    def _resolve_client_id(self, client_id: int | None) -> int | None:
        """Prefer an explicit ``client_id``, else fall back to the client default.

        VoiceLink's reseller-auth endpoints need to know which client a request is for.
        Callers can set a default once on the client and omit it per-call.
        """
        return client_id if client_id is not None else self._client.client_id

    @staticmethod
    def _clean(body: dict[str, Any]) -> dict[str, Any]:
        """Drop keys whose value is ``None`` so we only send what was set."""
        return {k: v for k, v in body.items() if v is not None}
