"""Call logs — per-call detail records and SIP packet captures."""

from __future__ import annotations

from typing import Any

from .base import Resource


class CallLogsResource(Resource):
    def details(self, call_id: str) -> dict[str, Any]:
        """Fetch the detail record for a single call."""
        return self._transport.request("GET", "/v1/call-log/details", params={"call_id": call_id})

    def pcap(self, call_id: str) -> Any:
        """Fetch the SIP capture (PCAP) reference/data for a call."""
        return self._transport.request("GET", "/v1/call-log/pcap", params={"call_id": call_id})
