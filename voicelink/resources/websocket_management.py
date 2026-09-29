"""WebSocket management — control a client's WebSocket bot connections."""

from __future__ import annotations

from typing import Any

from ..models import Page
from .base import Resource


class WebsocketManagementResource(Resource):
    def list(
        self,
        *,
        search: str | None = None,
        page: int = 1,
        per_page: int = 10,
    ) -> Page[dict[str, Any]]:
        """List WebSocket connections."""
        params = self._clean({"search": search, "page": page, "per_page": per_page})
        data = self._transport.request("GET", "/v1/websocket-management/list", params=params)
        return Page.from_payload(data, lambda d: d)

    def pause(self, client_id: int) -> dict[str, Any]:
        """Pause a client's WebSocket connection."""
        return self._transport.request("POST", f"/v1/websocket-management/pause/{client_id}")

    def resume(self, client_id: int) -> dict[str, Any]:
        """Resume a client's WebSocket connection."""
        return self._transport.request("POST", f"/v1/websocket-management/resume/{client_id}")

    def remove(self, client_id: int) -> dict[str, Any]:
        """Remove a client's WebSocket connection."""
        return self._transport.request("DELETE", f"/v1/websocket-management/remove/{client_id}")
