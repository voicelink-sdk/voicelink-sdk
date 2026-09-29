"""Call Routing — bind a DID to the handlers for its inbound and outbound calls.

Each DID has exactly one routing rule. Identify the DID by ``did_number`` or ``did_id``.
The ``inbound`` / ``outbound`` choices use the :class:`InboundRoute` / :class:`OutboundRoute`
enums so callers never deal with the raw integers (which the API also labels
inconsistently across endpoints).
"""

from __future__ import annotations

from ..enums import InboundRoute, OutboundRoute, Status
from ..models import CallRouting, Page
from .base import Resource


class CallRoutingResource(Resource):
    def create(
        self,
        *,
        did_number: str | None = None,
        did_id: int | None = None,
        inbound: InboundRoute | int,
        outbound: OutboundRoute | int,
        inbound_websocket_bot_id: int | None = None,
        inbound_sip_trunk_id: int | None = None,
        outbound_websocket_bot_id: int | None = None,
        outbound_sip_trunk_id: int | None = None,
        status: Status | int = Status.ACTIVE,
    ) -> CallRouting:
        """Create the routing rule for a DID.

        Provide the handler id that matches your choice — e.g. for
        ``inbound=InboundRoute.WEBSOCKET_BOT`` pass ``inbound_websocket_bot_id``.
        """
        if did_number is None and did_id is None:
            raise ValueError("Provide either did_number or did_id")

        body = self._clean(
            {
                "did_number": did_number,
                "did_id": did_id,
                "for_inbound_call": int(inbound),
                "for_outbound_call": int(outbound),
                "inbound_websocket_bot_id": inbound_websocket_bot_id,
                "inbound_sip_trunk_id": inbound_sip_trunk_id,
                "outbound_websocket_bot_id": outbound_websocket_bot_id,
                "outbound_sip_trunk_id": outbound_sip_trunk_id,
                "status": int(status),
            }
        )
        data = self._transport.request("POST", "/v1/call-routing/create", json=body)
        return CallRouting.from_dict(data or {})

    def list(self, *, client_id: int | None = None) -> Page[CallRouting]:
        """List routing rules visible to the account."""
        params = {"client_id": self._resolve_client_id(client_id)}
        data = self._transport.request("GET", "/v1/call-routing/list", params=params)
        return Page.from_payload(data, CallRouting.from_dict)

    def update(
        self,
        routing_id: int,
        *,
        inbound: InboundRoute | int,
        outbound: OutboundRoute | int,
        status: Status | int,
        inbound_websocket_bot_id: int | None = None,
        inbound_sip_trunk_id: int | None = None,
        outbound_websocket_bot_id: int | None = None,
        outbound_sip_trunk_id: int | None = None,
    ) -> CallRouting:
        """Update a routing rule. The DID cannot be changed once set."""
        body = self._clean(
            {
                "for_inbound_call": int(inbound),
                "for_outbound_call": int(outbound),
                "status": int(status),
                "inbound_websocket_bot_id": inbound_websocket_bot_id,
                "inbound_sip_trunk_id": inbound_sip_trunk_id,
                "outbound_websocket_bot_id": outbound_websocket_bot_id,
                "outbound_sip_trunk_id": outbound_sip_trunk_id,
            }
        )
        data = self._transport.request("POST", f"/v1/call-routing/update/{routing_id}", json=body)
        return CallRouting.from_dict(data or {})
