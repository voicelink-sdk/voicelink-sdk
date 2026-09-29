"""Agents — the human/desk agents a DID's calls can ring (distinct from AI agents)."""

from __future__ import annotations

from typing import Any

from ..enums import Status
from ..models import Page
from .base import Resource


class AgentsResource(Resource):
    def create(
        self,
        *,
        first_name: str,
        last_name: str,
        phone_number: str,
        remarks: str | None = None,
        status: Status | int = Status.ACTIVE,
    ) -> dict[str, Any]:
        """Create an agent."""
        body = self._clean(
            {
                "first_name": first_name,
                "last_name": last_name,
                "phone_number": phone_number,
                "remarks": remarks,
                "status": int(status),
            }
        )
        return self._transport.request("POST", "/v1/agent/create", json=body)

    def list(
        self,
        *,
        search: str | None = None,
        status: Status | int | None = None,
        reseller_id: int | None = None,
        page: int = 1,
        per_page: int = 10,
    ) -> Page[dict[str, Any]]:
        """List agents."""
        params = self._clean(
            {
                "search": search,
                "status": None if status is None else int(status),
                "reseller_id": reseller_id,
                "page": page,
                "per_page": per_page,
            }
        )
        data = self._transport.request("GET", "/v1/agent/list", params=params)
        return Page.from_payload(data, lambda d: d)

    def update(
        self,
        agent_id: int,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        phone_number: str | None = None,
        remarks: str | None = None,
        status: Status | int | None = None,
    ) -> dict[str, Any]:
        """Update an agent. Only the fields you pass are changed."""
        body = self._clean(
            {
                "first_name": first_name,
                "last_name": last_name,
                "phone_number": phone_number,
                "remarks": remarks,
                "status": None if status is None else int(status),
            }
        )
        return self._transport.request("POST", f"/v1/agent/update/{agent_id}", json=body)

    def delete(self, agent_id: int) -> dict[str, Any]:
        """Delete an agent."""
        return self._transport.request("DELETE", f"/v1/agent/delete/{agent_id}")
