"""Calls — trigger outbound calls via VoiceLink's ``add_lead`` endpoint.

The single API endpoint behaves as two different features, so the SDK exposes two
methods:

* :meth:`create` — dial one number now. Returns a :class:`LeadResult` with the queue id.
* :meth:`create_bulk` — enqueue many numbers as a background campaign. Returns a
  :class:`BulkLeadResult` with the accepted count.

A call requires the DID to already have an active outbound WebSocket bot configured.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..models import BulkLeadResult, LeadResult
from .base import Resource


class CallsResource(Resource):
    def create(
        self,
        *,
        did_number: str,
        customer_number: str,
        custom_parameters: Mapping[str, Any] | None = None,
        country_code: str | None = None,
        websocket_url: str | None = None,
        webhook_url: str | None = None,
        call_limit: int | None = None,
    ) -> LeadResult:
        """Dial a single number from ``did_number``.

        ``custom_parameters`` is passed as a dict and travels with the call; it is
        delivered back on the media ``start`` event and on webhooks. (VoiceLink also
        injects an ``outboundQueueId`` there, letting you correlate events to this call.)

        ``websocket_url`` / ``webhook_url`` optionally override the bot's defaults for
        just this call — useful for routing individual calls to different agents.
        """
        body = self._clean(
            {
                "did_number": did_number,
                "customer_number": customer_number,
                "country_code": country_code,
                "custom_parameters": _encode_params(custom_parameters),
                "websocket_url": websocket_url,
                "webhook_url": webhook_url,
                "call_limit": call_limit,
            }
        )
        data = self._transport.request("POST", "/v1/add_lead", json=body)
        return LeadResult.from_dict(data if isinstance(data, dict) else {"data": data})

    def create_bulk(
        self,
        *,
        did_number: str,
        leads: Sequence[Mapping[str, Any]],
        country_code: str | None = None,
        websocket_url: str | None = None,
        webhook_url: str | None = None,
        call_limit: int | None = None,
    ) -> BulkLeadResult:
        """Enqueue many numbers as a background campaign.

        Each item in ``leads`` is a mapping with at least ``customer_number`` and an
        optional ``custom_parameters`` dict, e.g.::

            client.calls.create_bulk(
                did_number="919484950416",
                leads=[
                    {"customer_number": "919000000001"},
                    {"customer_number": "919000000002",
                     "custom_parameters": {"campaign": "fall"}},
                ],
            )
        """
        body = self._clean(
            {
                "did_number": did_number,
                "leads": [_encode_lead(item) for item in leads],
                "country_code": country_code,
                "websocket_url": websocket_url,
                "webhook_url": webhook_url,
                "call_limit": call_limit,
            }
        )
        data = self._transport.request("POST", "/v1/add_lead", json=body)
        return BulkLeadResult.from_dict(data if isinstance(data, dict) else {"data": data})


def _encode_params(params: Mapping[str, Any] | None) -> str | None:
    """The API expects ``custom_parameters`` as a JSON *string*, not an object."""
    if params is None:
        return None
    return json.dumps(dict(params))


def _encode_lead(item: Mapping[str, Any]) -> dict[str, Any]:
    lead: dict[str, Any] = {"customer_number": item["customer_number"]}
    if item.get("custom_parameters") is not None:
        lead["custom_parameters"] = _encode_params(item["custom_parameters"])
    return lead
