"""DIDs — the phone numbers in the account's inventory.

List the numbers you own, find which are free to assign to a client, release a number,
and submit / track purchase requests. The full purchase checkout flow lives in
:class:`~voicelink.resources.purchase.PurchaseResource`.
"""

from __future__ import annotations

from typing import Any

from ..models import Did, Page
from .base import Resource


class DidsResource(Resource):
    def list(
        self,
        *,
        page: int = 1,
        per_page: int = 10,
        search: str | None = None,
        status: int | None = None,
        client_id: int | None = None,
    ) -> Page[Did]:
        """List purchased DIDs.

        For a reseller this returns all numbers they own; for a client, only the numbers
        assigned to them.
        """
        params = {
            "page": page,
            "per_page": per_page,
            "search": search,
            "status": status,
            "client_id": self._resolve_client_id(client_id),
        }
        data = self._transport.request("GET", "/v1/reseller/did/purchased", params=params)
        return Page.from_payload(data, Did.from_dict)

    def available_for_client(self) -> list[Did]:
        """List DIDs owned by the reseller that are not yet assigned to any client."""
        data = self._transport.request("GET", "/v1/reseller/client/available-dids")
        rows = data if isinstance(data, list) else (data or {}).get("data", [])
        return [Did.from_dict(r) for r in rows]

    def release(self, did_number: str) -> dict[str, Any]:
        """Release a DID back to the pool."""
        return self._transport.request(
            "POST", "/v1/reseller/did/release", json={"did_number": did_number}
        )

    def types(self) -> Any:
        """List the active DID types (used when requesting or purchasing numbers)."""
        return self._transport.request("GET", "/v1/reseller/did-types")

    def purchase_requests(self) -> Any:
        """List the reseller's DID purchase requests."""
        return self._transport.request("GET", "/v1/reseller/did-purchase-request")

    def request_purchase(
        self, *, did_type_id: int, dlt_confirmed: int, use_case: str
    ) -> dict[str, Any]:
        """Submit a DID purchase request."""
        body = {
            "did_type_id": did_type_id,
            "dlt_confirmed": dlt_confirmed,
            "use_case": use_case,
        }
        return self._transport.request("POST", "/v1/reseller/did-purchase-request", json=body)
