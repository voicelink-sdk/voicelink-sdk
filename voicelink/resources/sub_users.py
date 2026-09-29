"""Sub-users — additional logins under an account, each with scoped permissions."""

from __future__ import annotations

from typing import Any

from ..enums import Status
from ..models import Page
from .base import Resource


class SubUsersResource(Resource):
    def list(self, *, search: str | None = None) -> Page[dict[str, Any]]:
        """List sub-users."""
        params = self._clean({"search": search})
        data = self._transport.request("GET", "/v1/sub-user", params=params)
        return Page.from_payload(data, lambda d: d)

    def create(
        self,
        *,
        name: str,
        email: str,
        password: str,
        permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a sub-user."""
        body = self._clean(
            {
                "name": name,
                "email": email,
                "password": password,
                "permissions": permissions,
            }
        )
        return self._transport.request("POST", "/v1/sub-user", json=body)

    def get(self, sub_user_id: int) -> dict[str, Any]:
        """Get a sub-user."""
        return self._transport.request("GET", f"/v1/sub-user/{sub_user_id}")

    def update(
        self,
        sub_user_id: int,
        *,
        name: str,
        email: str,
        status: Status | int,
        password: str | None = None,
    ) -> dict[str, Any]:
        """Update a sub-user."""
        body = self._clean(
            {
                "name": name,
                "email": email,
                "status": int(status),
                "password": password,
            }
        )
        return self._transport.request("PUT", f"/v1/sub-user/{sub_user_id}", json=body)

    def delete(self, sub_user_id: int) -> dict[str, Any]:
        """Delete a sub-user."""
        return self._transport.request("DELETE", f"/v1/sub-user/{sub_user_id}")

    def sync_permissions(self, sub_user_id: int, *, permissions: list[str]) -> dict[str, Any]:
        """Replace a sub-user's permissions."""
        body = self._clean({"permissions": permissions})
        return self._transport.request("POST", f"/v1/sub-user/{sub_user_id}/permissions", json=body)
