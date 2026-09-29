"""Clients — reseller-side management of the clients under a reseller."""

from __future__ import annotations

from typing import Any

from .base import Resource


class ClientsResource(Resource):
    def list(self) -> Any:
        """List clients."""
        return self._transport.request("GET", "/v1/reseller/clients")

    def create(
        self,
        *,
        first_name: str,
        last_name: str,
        username: str,
        email: str,
        password: str,
        channel_count: int,
        phone: str | None = None,
        is_active: int = 1,
        negative_threshold: float | None = None,
        pulse_seconds: int | None = None,
        inbound_rate: float | None = None,
        outbound_rate: float | None = None,
        plan_type: str | None = None,
        wallet_balance: float | None = None,
        wallet_bypass: int | None = None,
    ) -> dict[str, Any]:
        """Create a client."""
        body = self._clean(
            {
                "first_name": first_name,
                "last_name": last_name,
                "username": username,
                "email": email,
                "password": password,
                "channel_count": channel_count,
                "phone": phone,
                "is_active": is_active,
                "negative_threshold": negative_threshold,
                "pulse_seconds": pulse_seconds,
                "inbound_rate": inbound_rate,
                "outbound_rate": outbound_rate,
                "plan_type": plan_type,
                "wallet_balance": wallet_balance,
                "wallet_bypass": wallet_bypass,
            }
        )
        return self._transport.request("POST", "/v1/reseller/client/create", json=body)

    def update(
        self,
        client_id: int,
        *,
        first_name: str,
        last_name: str,
        is_active: int,
        channel_count: int,
        username: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        password: str | None = None,
        negative_threshold: float | None = None,
        pulse_seconds: int | None = None,
        inbound_rate: float | None = None,
        outbound_rate: float | None = None,
        plan_type: str | None = None,
        wallet_balance: float | None = None,
        wallet_bypass: int | None = None,
    ) -> dict[str, Any]:
        """Update a client."""
        body = self._clean(
            {
                "first_name": first_name,
                "last_name": last_name,
                "is_active": is_active,
                "channel_count": channel_count,
                "username": username,
                "email": email,
                "phone": phone,
                "password": password,
                "negative_threshold": negative_threshold,
                "pulse_seconds": pulse_seconds,
                "inbound_rate": inbound_rate,
                "outbound_rate": outbound_rate,
                "plan_type": plan_type,
                "wallet_balance": wallet_balance,
                "wallet_bypass": wallet_bypass,
            }
        )
        return self._transport.request("POST", f"/v1/reseller/client/update/{client_id}", json=body)

    def delete(self, client_id: int) -> dict[str, Any]:
        """Delete a client."""
        return self._transport.request("DELETE", f"/v1/reseller/client/delete/{client_id}")

    def map_did(
        self,
        *,
        client_id: int,
        did_id: int,
        call_recording: int,
        user_status: int | None = None,
        user_expiry_date: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Map a DID to a client."""
        body = self._clean(
            {
                "client_id": client_id,
                "did_id": did_id,
                "call_recording": call_recording,
                "user_status": user_status,
                "user_expiry_date": user_expiry_date,
                "description": description,
            }
        )
        return self._transport.request("POST", "/v1/reseller/client/map-did", json=body)

    def allocate_wallet(
        self,
        client_id: int,
        *,
        amount: float,
        description: str,
    ) -> dict[str, Any]:
        """Allocate wallet funds to a client."""
        body = self._clean({"amount": amount, "description": description})
        return self._transport.request(
            "POST", f"/v1/reseller/client/allocate-wallet/{client_id}", json=body
        )

    def available_dids(self) -> Any:
        """List DIDs available to allocate to clients."""
        return self._transport.request("GET", "/v1/reseller/client/available-dids")
