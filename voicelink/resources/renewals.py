"""Renewals — renew purchased DIDs and channels."""

from __future__ import annotations

from typing import Any

from .base import Resource


class RenewalsResource(Resource):
    def list(self) -> Any:
        """List renewable items."""
        return self._transport.request("GET", "/v1/reseller/renew/list")

    def summary(
        self,
        *,
        did_purchase_ids: list[int] | None = None,
        channel_purchase_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Get a renewal summary."""
        body = self._clean(
            {
                "did_purchase_ids": did_purchase_ids,
                "channel_purchase_ids": channel_purchase_ids,
            }
        )
        return self._transport.request("POST", "/v1/reseller/renew/summary", json=body)

    def confirm(
        self,
        *,
        renew_for_client: bool | None = None,
        did_purchase_ids: list[int] | None = None,
        channel_purchase_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Confirm a renewal."""
        body = self._clean(
            {
                "renew_for_client": renew_for_client,
                "did_purchase_ids": did_purchase_ids,
                "channel_purchase_ids": channel_purchase_ids,
            }
        )
        return self._transport.request("POST", "/v1/reseller/renew/confirm", json=body)
