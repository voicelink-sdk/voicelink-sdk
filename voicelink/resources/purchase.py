"""Purchase — the DID purchase flow (find, lock, add channels, promocode, confirm)."""

from __future__ import annotations

from typing import Any

from ..models import Page
from .base import Resource


class PurchaseResource(Resource):
    def available_dids(
        self,
        *,
        country_code: str,
        did_type: str,
        months: int,
        number: str | None = None,
        page: int = 1,
        per_page: int = 10,
    ) -> Page[dict[str, Any]]:
        """List DIDs available to purchase."""
        params = self._clean(
            {
                "country_code": country_code,
                "type": did_type,
                "months": months,
                "number": number,
                "page": page,
                "per_page": per_page,
            }
        )
        data = self._transport.request("GET", "/v1/reseller/purchase/dids", params=params)
        return Page.from_payload(data, lambda d: d)

    def lock_did(
        self,
        *,
        months: int,
        did_ids: list[int],
        order_id: int | None = None,
    ) -> dict[str, Any]:
        """Lock DIDs for an order."""
        body = self._clean(
            {
                "months": months,
                "did_ids": did_ids,
                "order_id": order_id,
            }
        )
        return self._transport.request("POST", "/v1/reseller/purchase/lock-did", json=body)

    def add_channel(
        self,
        *,
        channel_count: int,
        months: int,
        order_id: int | None = None,
    ) -> dict[str, Any]:
        """Add channels to an order."""
        body = self._clean(
            {
                "channel_count": channel_count,
                "months": months,
                "order_id": order_id,
            }
        )
        return self._transport.request("POST", "/v1/reseller/purchase/add-channel", json=body)

    def promocode(
        self,
        *,
        order_id: int,
        action: str,
        code: str | None = None,
    ) -> dict[str, Any]:
        """Apply or remove a promocode on an order."""
        body = self._clean(
            {
                "order_id": order_id,
                "action": action,
                "code": code,
            }
        )
        return self._transport.request("POST", "/v1/reseller/purchase/promocode", json=body)

    def summary(self, order_id: int) -> dict[str, Any]:
        """Get an order summary."""
        return self._transport.request("GET", f"/v1/reseller/purchase/summary/{order_id}")

    def confirm(self, *, order_id: int) -> dict[str, Any]:
        """Confirm an order."""
        return self._transport.request(
            "POST", "/v1/reseller/purchase/confirm", json={"order_id": order_id}
        )
