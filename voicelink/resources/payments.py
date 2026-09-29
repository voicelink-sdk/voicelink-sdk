"""Payments — top-ups awaiting invoicing and their reconciliation."""

from __future__ import annotations

from typing import Any

from .base import Resource


class PaymentsResource(Resource):
    def new_payments(self) -> Any:
        """List successful top-ups awaiting an invoice (Tally)."""
        return self._transport.request("GET", "/v1/get-new-payments")

    def update_payments(self, data: list[dict[str, Any]]) -> dict[str, Any]:
        """Mark payments as reconciled/invoiced."""
        return self._transport.request("POST", "/v1/update-payments", json={"data": data})
