"""Sounds — audio prompts (welcome, busy, off-time) uploaded to the account."""

from __future__ import annotations

from typing import Any

from ..enums import Status
from ..models import Page
from .base import Resource


class SoundsResource(Resource):
    def create(self, **fields: Any) -> dict[str, Any]:
        """Create a sound. Audio is uploaded — some deployments need multipart or the portal."""
        return self._transport.request("POST", "/v1/sound/create", json=self._clean(fields))

    def list(
        self,
        *,
        search: str | None = None,
        status: Status | int | None = None,
        type: str | None = None,
        reseller_id: int | None = None,
        page: int = 1,
        per_page: int = 10,
    ) -> Page[dict[str, Any]]:
        """List sounds."""
        params = self._clean(
            {
                "search": search,
                "status": None if status is None else int(status),
                "type": type,
                "reseller_id": reseller_id,
                "page": page,
                "per_page": per_page,
            }
        )
        data = self._transport.request("GET", "/v1/sound/list", params=params)
        return Page.from_payload(data, lambda d: d)

    def update(self, sound_id: int, **fields: Any) -> dict[str, Any]:
        """Update a sound. Only the fields you pass are changed."""
        return self._transport.request(
            "POST", f"/v1/sound/update/{sound_id}", json=self._clean(fields)
        )

    def delete(self, sound_id: int) -> dict[str, Any]:
        """Delete a sound."""
        return self._transport.request("DELETE", f"/v1/sound/delete/{sound_id}")
