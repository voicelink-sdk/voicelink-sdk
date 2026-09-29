"""Call settings — how a DID routes calls (agents, sounds, time setting)."""

from __future__ import annotations

from typing import Any

from ..enums import Status
from ..models import Page
from .base import Resource


class CallSettingsResource(Resource):
    def create(
        self,
        *,
        routing_type: int | None = None,
        status: Status | int | None = None,
        busy_sound_id: int | None = None,
        offtime_sound_id: int | None = None,
        time_setting_id: int | None = None,
        welcome_sound_id: int | None = None,
        agents: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Create a call setting."""
        body = self._clean(
            {
                "routing_type": routing_type,
                "status": None if status is None else int(status),
                "busy_sound_id": busy_sound_id,
                "offtime_sound_id": offtime_sound_id,
                "time_setting_id": time_setting_id,
                "welcome_sound_id": welcome_sound_id,
                "agents": agents,
            }
        )
        return self._transport.request("POST", "/v1/call-setting/create", json=body)

    def list(
        self,
        *,
        did_id: int | None = None,
        status: Status | int | None = None,
        routing_type: int | None = None,
        reseller_id: int | None = None,
        page: int = 1,
        per_page: int = 10,
    ) -> Page[dict[str, Any]]:
        """List call settings."""
        params = self._clean(
            {
                "did_id": did_id,
                "status": None if status is None else int(status),
                "routing_type": routing_type,
                "reseller_id": reseller_id,
                "page": page,
                "per_page": per_page,
            }
        )
        data = self._transport.request("GET", "/v1/call-setting/list", params=params)
        return Page.from_payload(data, lambda d: d)

    def update(
        self,
        call_setting_id: int,
        *,
        routing_type: int | None = None,
        status: Status | int | None = None,
        busy_sound_id: int | None = None,
        offtime_sound_id: int | None = None,
        time_setting_id: int | None = None,
        welcome_sound_id: int | None = None,
        agents: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Update a call setting. Only the fields you pass are changed."""
        body = self._clean(
            {
                "routing_type": routing_type,
                "status": None if status is None else int(status),
                "busy_sound_id": busy_sound_id,
                "offtime_sound_id": offtime_sound_id,
                "time_setting_id": time_setting_id,
                "welcome_sound_id": welcome_sound_id,
                "agents": agents,
            }
        )
        return self._transport.request(
            "POST", f"/v1/call-setting/update/{call_setting_id}", json=body
        )

    def delete(self, call_setting_id: int) -> dict[str, Any]:
        """Delete a call setting."""
        return self._transport.request("DELETE", f"/v1/call-setting/delete/{call_setting_id}")
