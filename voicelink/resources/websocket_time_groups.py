"""WebSocket time groups — scheduled windows governing WebSocket bot availability."""

from __future__ import annotations

from typing import Any

from ..enums import Status
from ..models import Page
from .base import Resource


class WebsocketTimeGroupsResource(Resource):
    def create(
        self,
        *,
        group_name: str,
        client_ids: list[int],
        schedule: list[Any],
        status: Status | int = Status.ACTIVE,
    ) -> dict[str, Any]:
        """Create a WebSocket time group."""
        body = self._clean(
            {
                "group_name": group_name,
                "client_ids": client_ids,
                "schedule": schedule,
                "status": int(status),
            }
        )
        return self._transport.request("POST", "/v1/websocket-time-group/create", json=body)

    def list(
        self,
        *,
        search: str | None = None,
        status: Status | int | None = None,
        reseller_id: int | None = None,
        page: int = 1,
        per_page: int = 10,
    ) -> Page[dict[str, Any]]:
        """List WebSocket time groups."""
        params = self._clean(
            {
                "search": search,
                "status": None if status is None else int(status),
                "reseller_id": reseller_id,
                "page": page,
                "per_page": per_page,
            }
        )
        data = self._transport.request("GET", "/v1/websocket-time-group/list", params=params)
        return Page.from_payload(data, lambda d: d)

    def update(
        self,
        group_id: int,
        *,
        group_name: str | None = None,
        status: Status | int | None = None,
        client_ids: list[int] | None = None,
        schedule: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Update a WebSocket time group. Only the fields you pass are changed."""
        body = self._clean(
            {
                "group_name": group_name,
                "status": None if status is None else int(status),
                "client_ids": client_ids,
                "schedule": schedule,
            }
        )
        return self._transport.request(
            "POST", f"/v1/websocket-time-group/update/{group_id}", json=body
        )

    def delete(self, group_id: int) -> dict[str, Any]:
        """Delete a WebSocket time group."""
        return self._transport.request("DELETE", f"/v1/websocket-time-group/delete/{group_id}")
