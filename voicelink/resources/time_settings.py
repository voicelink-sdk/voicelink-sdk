"""Time settings — named schedules that gate when a DID's calls route to agents."""

from __future__ import annotations

from typing import Any

from ..enums import Status
from ..models import Page
from .base import Resource


class TimeSettingsResource(Resource):
    def create(
        self,
        *,
        group_name: str,
        schedule: list[Any],
        status: Status | int = Status.ACTIVE,
        agent_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Create a time setting."""
        body = self._clean(
            {
                "group_name": group_name,
                "schedule": schedule,
                "status": int(status),
                "agent_ids": agent_ids,
            }
        )
        return self._transport.request("POST", "/v1/time-setting/create", json=body)

    def list(
        self,
        *,
        search: str | None = None,
        status: Status | int | None = None,
        reseller_id: int | None = None,
        page: int = 1,
        per_page: int = 10,
    ) -> Page[dict[str, Any]]:
        """List time settings."""
        params = self._clean(
            {
                "search": search,
                "status": None if status is None else int(status),
                "reseller_id": reseller_id,
                "page": page,
                "per_page": per_page,
            }
        )
        data = self._transport.request("GET", "/v1/time-setting/list", params=params)
        return Page.from_payload(data, lambda d: d)

    def update(
        self,
        time_setting_id: int,
        *,
        group_name: str | None = None,
        status: Status | int | None = None,
        agent_ids: list[int] | None = None,
        schedule: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Update a time setting. Only the fields you pass are changed."""
        body = self._clean(
            {
                "group_name": group_name,
                "status": None if status is None else int(status),
                "agent_ids": agent_ids,
                "schedule": schedule,
            }
        )
        return self._transport.request(
            "POST", f"/v1/time-setting/update/{time_setting_id}", json=body
        )

    def delete(self, time_setting_id: int) -> dict[str, Any]:
        """Delete a time setting."""
        return self._transport.request("DELETE", f"/v1/time-setting/delete/{time_setting_id}")
